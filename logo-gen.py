import asyncio
from cascade_base import Cascade
from cascade_steps import *

BRAINSTORM_TEMPLATE = '''Let's brainstorm visual ideas for a logo representing the Cascade system.

Key aspects to consider:
- Cascade is a streaming pipeline system for content generation
- Data flows through Steps via named Streams
- Multiple Steps can consume from the same Stream
- The system enables parallel processing and load balancing
- Cascade IDs track data lineage through the pipeline

Some questions to explore:
- What visual metaphors could represent streaming data flow?
- How might we show the relationship between Steps and Streams?
- What colors and shapes could convey the system's parallel nature?
- How can we visually represent the transformation of data?

Please brainstorm creative visual concepts that could work as a logo, considering:
1. Core metaphors and symbolism
2. Potential color schemes
3. Shape language and geometry
4. Overall composition
5. How to incorporate the text "CASCADE"

Be specific and detailed in describing potential visual approaches.'''

IMAGE_TEMPLATE = '''A minimalist, professional logo design with the text "CASCADE" prominently featured. {{concept}}

Style: Clean, modern, technical
Colors: {{colors}}
Composition: {{composition}}'''

async def main():
    # Create pipeline
    cascade = Cascade(project_name='logo-gen')
    
    # Define steps
    await cascade.step(StepIdeaSource(
        name='generate_scenario',
        streams={'output': 'vars'},
        params={
            'count': 5,
            'schema': {
                'concept': {'constant': ''},
                'colors': {'constant': ''},
                'composition': {'constant': ''}
            }
        }
    ))
    
    await cascade.step(StepExpandTemplate(
        name='expand_brainstorm',
        streams={
            'input': 'vars:1',
            'output': 'brainstorm_prompts'
        },
        params={
            'template': BRAINSTORM_TEMPLATE
        }
    ))
    
    await cascade.step(StepLLMCompletion(
        name='generate_concepts',
        streams={
            'input': 'brainstorm_prompts:1',
            'output': 'raw_concepts'
        },
        params={
            'model': 'gemma-2-9b-it-exl2-6.0bpw',
            'sampler': {
                'temperature': 0.7,
                'max_tokens': 1024
            }
        }
    ))

    await cascade.step(StepLLMCompletion(
        name='extract_visual',
        streams={
            'input': 'raw_concepts:1',
            'output': 'visual_specs'
        },
        params={
            'model': 'gemma-2-9b-it-exl2-6.0bpw',
            'schema_mode': 'openai-json',
            'sampler': {
                'temperature': 0.4,
                'max_tokens': 512
            }
        }
    ))

    await cascade.step(StepJSONParser(
        name='parse_visual',
        streams={
            'input': 'visual_specs:1',
            'output': 'parsed_specs'
        }
    ))
    
    await cascade.step(StepExpandTemplate(
        name='expand_image',
        streams={
            'input': 'parsed_specs:1',
            'output': 'image_prompts'
        },
        params={
            'template': IMAGE_TEMPLATE
        }
    ))
    
    await cascade.step(StepText2Image(
        name='generate_image',
        streams={
            'input': 'image_prompts:1',
            'output': 'images'
        },
        params={
            'width': 512,
            'height': 512,
            'steps': 20
        }
    ))
    
    await cascade.step(StepJSONSink(
        name='export_json',
        streams={
            'input': 'images:1'
        },
        params={
            'output_dir': 'output/logos'
        }
    ))
    
    # Run pipeline
    await cascade.run()

if __name__ == '__main__':
    asyncio.run(main())
