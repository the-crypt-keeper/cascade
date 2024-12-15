from cascade_base import *
import cascade_steps
import importlib
from typing import Type, List

class Cascade:
    def __init__(self, config_path: Path, debug: bool = False):
        self.config_path = config_path
        self.storage = SQLiteStorage(str(config_path.with_suffix('.db')))
        self.manager = CascadeManager(self.storage, debug=debug)
        self.steps: List[cascade_steps.Step] = []
                
    def step(self, step: 'cascade_steps.Step'):
        """Register and setup a step"""
        step.setup(self.manager)
        self.steps.append(step)

    def _import_step_class(self, class_name: str) -> Type[cascade_steps.Step]:
        """Dynamically import a step class"""
        module_path, class_name = class_name.rsplit('.', 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
        
    async def setup(self):
        """Load config and initialize all steps"""
        # Load and resolve configuration
        loader = CascadeLoader(self.config_path)
        config = loader.load()
        
        # Create all streams first
        streams = set()
        for step_config in config['steps'].values():
            for stream_spec in step_config['streams'].values():
                # Strip weight if present
                stream_name = stream_spec.split(':')[0]
                streams.add(stream_name)
                
        for stream in streams:
            self.manager.get_stream(stream)
            
        # Create and setup all steps
        for step_name, step_config in config['steps'].items():
            # Import step class
            step_class = self._import_step_class(step_config['class'])
            
            # Create step instance
            step = step_class(
                name=step_name,
                streams=step_config['streams'],
                params=step_config['params']
            )
            
            # Setup step
            await step.setup(self.manager)
            self.steps.append(step)
            
    async def run(self):
        # Restore any existing state
        await self.manager.restore_state()
        
        """Run all steps until completion"""
        try:
            # Start all steps
            tasks = [asyncio.create_task(step.run()) for step in self.steps]
            
            # Wait for completion
            await self.manager.wait_for_completion()
            
            # Cancel all tasks
            for task in tasks:
                task.cancel()
                
            # Wait for tasks to finish
            await asyncio.gather(*tasks, return_exceptions=True)
            
        finally:
            # Ensure steps are shutdown
            for step in self.steps:
                await step.shutdown()
