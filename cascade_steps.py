from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio
import random
from cascade_base import *
from jinja2 import Template
from pathlib import Path
import hashlib
import time
from llm_utils import build_tokenizer, universal_llm_request

class Step(ABC):
    def __init__(self, name: str, streams: Dict[str, str], params: Dict[str, Any]):
        self.name = name
        self.stream_configs = streams
        self.params = params
        self.manager: Optional['CascadeManager'] = None
        self.streams: Dict[str, Stream] = {}
        
    async def setup(self, manager: 'CascadeManager'):
        """Initialize step with cascade manager"""
        self.manager = manager
        self.manager.register_step(self.name)
        
        # Setup all streams
        for port_name, stream_spec in self.stream_configs.items():
            # Check if this is a consumer stream
            if ':' in stream_spec:
                stream_name, weight = stream_spec.rsplit(':', 1)
                stream = self.manager.get_stream(stream_name)
                stream.register_consumer(self.name, int(weight))
            else:
                stream = self.manager.get_stream(stream_spec)
            self.streams[port_name] = stream
            
        await self._setup()
        
    async def _setup(self):
        """Optional step-specific setup"""
        pass
        
    @abstractmethod
    async def run(self):
        """Main processing loop"""
        pass

    async def shutdown(self):
        """Cleanup resources"""
        pass

class TransformStep(Step):
    async def run(self):
        """Main processing loop"""
        while True:
            try:
                # Mark as idle before waiting
                self.manager.mark_step_idle(self.name)
                msg = await self.streams['input'].get(self.name)
                # Mark as active while processing
                self.manager.mark_step_active(self.name)
                
                # Generate new cascade ID for our output
                out_cascade_id = msg.derive_cascade_id(self.name)
                
                # Check if we've already processed this
                if not await self.streams['output'].check_exists(out_cascade_id):
                    # Process the message
                    result = await self.process(msg.payload)
                    if result is not None:
                        # Create and send output message
                        out_msg = Message(
                            cascade_id=out_cascade_id,
                            payload=result,
                            metadata={'source_step': self.name}
                        )
                        await self.streams['output'].put(out_msg)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in {self.name}: {e}")

    @abstractmethod
    async def process(self, data: Any) -> Any:
        """Transform input data into output data"""
        pass

class SourceStep(Step):
    async def run(self):
        """Generate initial items"""
        try:
            self.manager.mark_step_active(self.name)
            
            max_items = int(self.params.get('max_items', 1))
            # Generate deterministic IDs
            for i in range(max_items):
                cascade_id = f"{self.name}:count={i}"
                
                # Check if we've already generated this
                if not await self.streams['output'].check_exists(cascade_id):
                    # Generate new item
                    data = await self.generate()
                    if data is not None:
                        msg = Message(
                            cascade_id=cascade_id,
                            payload=data,
                            metadata={'source_step': self.name}
                        )
                        await self.streams['output'].put(msg)
            
            # Mark as idle once we've generated everything
            self.manager.mark_step_idle(self.name)
            
        except Exception as e:
            print(f"Error in {self.name}: {e}")
            self.manager.mark_step_idle(self.name)

    @abstractmethod
    async def generate(self) -> Any:
        """Generate a new item"""
        pass

class SinkStep(Step):
    async def run(self):
        """Process input items"""
        while True:
            try:
                # Mark as idle before waiting
                self.manager.mark_step_idle(self.name)
                msg = await self.streams['input'].get(self.name)
                # Mark as active while processing
                self.manager.mark_step_active(self.name)
                
                # Process the message
                await self.sink(msg)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in {self.name}: {e}")

    @abstractmethod
    async def sink(self, data: Message):
        """Process a single item"""
        pass
    
class StepIdeaSource(SourceStep):
    async def _setup(self):
        if 'count' not in self.params:
            raise ValueError(f"StepIdeaSource {self.name} requires 'count' parameter")
        if 'schema' not in self.params:
            raise ValueError(f"StepIdeaSource {self.name} requires 'schema' parameter")

    async def generate(self) -> Dict[str, Any]:
        """Generate a new scenario by processing schema definitions"""
        results = []
        count = int(self.params['count'])
        
        for _ in range(count):
            result = {}
            for key, param in self.params['schema'].items():
                if 'sample' in param:
                    source = param['sample']
                    sample_count = int(param.get('count', 1))
                    samples = random.sample(source, sample_count)
                    
                    # Return single item unless count > 1 or always_array is True
                    if sample_count == 1 and not param.get('always_array', False):
                        result[key] = samples[0]
                    else:
                        result[key] = samples
                        
                elif 'constant' in param:
                    result[key] = param['constant']
            
            results.append(result)
            
        return results[0] if count == 1 else results
    
class StepExpandTemplate(TransformStep):
    async def _setup(self):
        # Create template once during setup
        self.template = Template(self.params['template'])

    async def process(self, data: Any) -> str:
        """Expand template using input data as context"""
        return self.template.render(**data)
    
class StepLLMCompletion(TransformStep):
    async def _setup(self):
        """Initialize LLM completion parameters"""
        self.model = self.params.get('model')
        self.tokenizer_name = self.params.get('tokenizer')
        self.sampler = self.params.get('sampler', { 'temperature': 1.0, 'max_tokens': 2048 })
        
        if not self.model:
            raise Exception(f"LLMCompletion {self.name} requires model parameter.")
            
        self.completion_tokenizer = build_tokenizer(self.tokenizer_name) if self.tokenizer_name else None

    async def process(self, data: Any) -> Any:
        """Process input through LLM"""
        messages = [{'role': 'user', 'content': data}]
        
        if self.completion_tokenizer:
            messages = [{
                "role": "user", 
                "content": self.completion_tokenizer.apply_chat_template(
                    messages, 
                    tokenize=False, 
                    add_generation_prompt=True, 
                    bos_token=''
                )
            }]
            
        answers = await universal_llm_request(
            self.completion_tokenizer is not None,
            self.model,
            messages,
            self.sampler,
            1
        )
        
        if answers:
            return answers[0]
        return None

class StepJSONSink(SinkStep):
    async def _setup(self):
        # Ensure output directory exists
        self.output_dir = Path(self.params.get('output_dir', '.'))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _make_filename(self, cascade_id: str) -> str:
        """Create a stable, safe filename from a cascade ID"""
        return hashlib.md5(cascade_id.encode('utf-8')).hexdigest() + '.json'

    async def sink(self, msg: Message):
        """Write JSON file containing full cascade history"""
        # Get the full cascade history
        history = await self.manager.unroll(msg)
        
        # Generate output filename using MD5 hash
        filename = self.output_dir / self._make_filename(msg.cascade_id)
        
        # Write JSON file
        with open(filename, 'w') as f:
            # Include original cascade_id in output for reference
            json.dump({
                'cascade_id': msg.cascade_id,
                'history': history
            }, f, indent=2)
