from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio
import random
import time
from jinja2 import Template
from pathlib import Path
import hashlib
import time
import aiohttp

from cascade_base import *
from cascade_utils import build_tokenizer, universal_llm_request

class Step(ABC):
    def __init__(self, name: str, streams: Dict[str, str], params: Dict[str, Any] = {}):
        self.name = name
        self.stream_configs = streams
        self.params = params
        self.manager: Optional['CascadeManager'] = None
        self.streams: Dict[str, Stream] = {}
        
    async def setup(self, manager: 'CascadeManager'):
        """Initialize step with cascade manager"""
        self.manager = manager
        
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
    def __init__(self, name: str, streams: Dict[str, str], params: Dict[str, Any] = {}):
        super().__init__(name, streams, params)
        self.parallel = int(params.get('parallel', 1))
        
    async def worker(self, worker_id: int):
        """Individual worker process"""
        step_id = f"{self.name}:worker{worker_id}"
        while True:
            try:
                # Mark as idle before waiting
                self.manager.mark_step_idle(step_id)
                msg = await self.streams['input'].get(self.name)
                # Mark as active while processing
                self.manager.mark_step_active(step_id)
                
                # Process the message
                result = await self.process(msg)
                
                # Handle simple cases
                if result is not None:
                    out_cascade_id = msg.derive_cascade_id(self.name)
                    if not await self.streams['output'].check_exists(out_cascade_id):
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

    async def run(self):
        """Spawn parallel workers"""
        workers = [asyncio.create_task(self.worker(i)) for i in range(self.parallel)]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    @abstractmethod
    async def process(self, msg: Message) -> Any:
        """Process input message and optionally return dict for default output handling"""
        pass

class SourceStep(Step):
    async def run(self):
        """Generate initial items"""
        try:
            self.manager.mark_step_active(self.name)
            
            count = int(self.params.get('count', 1))
            # Generate deterministic IDs
            for i in range(count):
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
        if 'schema' not in self.params:
            raise ValueError(f"StepIdeaSource {self.name} requires 'schema' parameter")

    async def generate(self) -> Dict[str, Any]:
        """Generate a new scenario by processing schema definitions"""
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
                
        return result
    
class StepExpandTemplate(TransformStep):
    async def _setup(self):
        # Create template once during setup
        self.template = Template(self.params['template'])

    async def process(self, msg: Message) -> dict:
        """Expand template using input data as context"""
        payload = msg.payload if isinstance(msg.payload, dict) else { "input": msg.payload }
        return self.template.render(**payload)

class StepLLMCompletion(TransformStep):
    async def _setup(self):
        """Initialize LLM completion parameters"""
        self.model = self.params.get('model')
        self.tokenizer_name = self.params.get('tokenizer')
        self.schema_mode = self.params.get('schema_mode', 'none')
        self.schema_json = self.params.get('schema_json')
        self.sampler = self.params.get('sampler', { 'temperature': 1.0, 'max_tokens': 2048 }).copy()

        if not self.model:
            raise Exception(f"LLMCompletion {self.name} requires model parameter.")

        # Handle schema modes
        if self.schema_mode == "none":
            pass
        elif self.schema_mode == "openai-schema":
            self.sampler['response_format'] = {
                'type': "json_schema",
                'json_schema': {
                    "strict": True,
                    "name": "Result",
                    "schema": self.schema_json
                }
            }
        elif self.schema_mode == "openai-json":
            self.sampler['response_format'] = { 'type': "json_object" }
        elif self.schema_mode == "vllm":
            self.sampler['guided_json'] = self.schema_json
        elif self.schema_mode == "llama":
            self.sampler['json_schema'] = self.schema_json
        else:
            raise Exception(f"Invalid schema_mode: {self.schema_mode}")
            
        self.completion_tokenizer = build_tokenizer(self.tokenizer_name) if self.tokenizer_name else None

    async def process(self, msg: Message) -> None:
        """Process input through LLM and create output messages"""
        
        # Check if output0 for this model already exists.
        out0_cascade_id = msg.derive_cascade_id(self.name, index=0, model=self.model)
        if await self.streams['output'].check_exists(out0_cascade_id):
            return

        messages = [{'role': 'user', 'content': msg.payload}]
        
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
            self.sampler
        )
        
        if answers:
            # Create output message for each answer
            for i, answer in enumerate(answers):
                out_msg = Message(
                    cascade_id=msg.derive_cascade_id(self.name, index=i, model=self.model),
                    payload=answer,
                    metadata={'source_step': self.name}
                )
                await self.streams['output'].put(out_msg)

class StepJSONParser(TransformStep):
    async def _setup(self):
        """Initialize parser parameters"""
        self.first_key = self.params.get('first_key', False)
        self.explode_list = self.params.get('explode_list')
        self.explode_keys = self.params.get('explode_keys')

    async def process(self, msg: Message) -> None:
        data = msg.payload
        if not isinstance(data, str):
            return None
        
        # Find JSON boundaries
        sidx = data.find('{')
        eidx = data.rfind('}')
        
        if sidx == -1 or eidx == -1:
            print(f"JSON parse failed in {self.name}: {data}")
            return None

        try:
            result = json.loads(data[sidx:eidx+1])
        except json.JSONDecodeError:
            print(f"JSON parse failed in {self.name}: {data}")
            return None

        outputs = []
        
        # Handle first_key option
        if self.first_key and isinstance(result, dict) and len(result) > 0:
            first_key = next(iter(result))
            outputs.append(result[first_key])
        
        # Handle explode_list option
        elif self.explode_list and isinstance(result, dict):
            target_list = result.get(self.explode_list)
            if isinstance(target_list, list):
                outputs.extend(target_list)
        
        # Handle explode_keys option
        elif self.explode_keys and isinstance(result, dict):
            for key in self.explode_keys:
                if key in result:
                    outputs.append(result[key])
        
        # Default case - return full result
        else:
            outputs.append(result)

        # Output each result as a separate message
        for i, output in enumerate(outputs):
            # Generate unique cascade ID for each output
            out_cascade_id = msg.derive_cascade_id(self.name, index=i)
            
            # Check if we've already processed this
            if not await self.streams['output'].check_exists(out_cascade_id):
                out_msg = Message(
                    cascade_id=out_cascade_id,
                    payload=output,
                    metadata={'source_step': self.name}
                )
                await self.streams['output'].put(out_msg)

class StepText2Image(TransformStep):
    async def _setup(self):
        """Initialize image generation parameters"""
        if 'api_url' not in self.params:
            raise ValueError(f"StepText2Image {self.name} requires 'api_url' parameter")
        
        self.api_url = self.params['api_url']
        self.width = int(self.params.get('width', 512))
        self.height = int(self.params.get('height', 512))
        self.steps = int(self.params.get('steps', 20))

    async def process(self, msg: Message) -> Dict[str, Any]:
        # Check if we've already processed this
        if await self.streams['output'].check_exists(msg.derive_cascade_id(self.name)): return

        """Generate image from text prompt"""
        payload = {
            "prompt": msg.payload,
            "steps": self.steps,
            "width": self.width,
            "height": self.height
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/sdapi/v1/txt2img",
                json=payload
            ) as response:
                if response.status != 200:
                    raise Exception(f"Image API request failed with status code {response.status}")
                    
                result = await response.json()
        
        return {
            'image': result['images'][0],
            'metadata': {
                'timestamp': time.time(),
                'width': self.width,
                'height': self.height,
                'steps': self.steps
            }
        }

class StepJSONSink(SinkStep):
    async def _setup(self):
        # Ensure output directory exists
        self.output_dir = Path(self.params.get('output_dir', '.'))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _make_filename(self, cascade_id: str) -> str:
        """Create a stable, safe filename from a cascade ID"""
        return hashlib.md5(cascade_id.encode('utf-8')).hexdigest() + '.json'

    async def sink(self, msg: Message):
        """Write JSON file containing full cascade history and save images"""
        # Get the full cascade history
        history = await self.manager.unroll(msg)
        
        # Generate base filename using MD5 hash
        base_hash = self._make_filename(msg.cascade_id).replace('.json', '')
        
        # Save any images to PNG files
        for step, data in history.items():
            if 'image' in data:
                # Save image data to PNG file
                image_filename = f"{base_hash}_{step}.png"
                image_path = self.output_dir / image_filename
                
                # Decode base64 image and write to file
                import base64
                image_data = base64.b64decode(data['image'])
                with open(image_path, 'wb') as f:
                    f.write(image_data)
                    
                # Replace image data with filename
                data['image'] = image_filename
        
        # Write JSON file with modified history
        json_path = self.output_dir / f"{base_hash}.json"
        with open(json_path, 'w') as f:
            json.dump({
                'cascade_id': msg.cascade_id,
                'history': history
            }, f, indent=2)

class StepConsoleSink(SinkStep):
    async def sink(self, msg: Message):
        """Write message payload to console with cascade ID header"""
        print(f"\n=== Message: {msg.cascade_id} ===")
        if isinstance(msg.payload, (dict, list)):
            print(json.dumps(msg.payload, indent=2))
        else:
            print(msg.payload)
