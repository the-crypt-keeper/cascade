import asyncio
from cascade_base import Cascade
from cascade_steps import *

# Load assets
BASIC_WORDS = open('assets/basic.txt').read().splitlines()
ADVANCED_WORDS = open('assets/advanced.txt').read().splitlines()

BRAINSTORM_TEMPLATE = '''Let's brainstorm visual ideas for a logo representing the Cascade system.

To spark our imagination, we'll use these random words as inspiration: {{random_basic_words|join(', ')}}, {{random_advanced_words|join(', ')}}

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

EXTRACT_TEMPLATE = '''Given the brainstorming output below, extract specific visual design elements for a logo:

<input>
{{input}}
</input>

Format your response as a JSON object with these fields:
{
  "concept": "Brief description of the core visual concept",
  "colors": "Specific color palette description",
  "composition": "Description of layout and arrangement"
}

Reply with only the JSON object.'''

IMAGE_TEMPLATE = '''A minimalist, professional logo design with the text "CASCADE" prominently featured.

Core Concept: {{concept}}
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
                'random_basic_words': {
                    'sample': BASIC_WORDS,
                    'count': 3
                },
                'random_advanced_words': {
                    'sample': ADVANCED_WORDS,
                    'count': 3
                }
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

    await cascade.step(StepExpandTemplate(
        name='expand_extract',
        streams={
            'input': 'raw_concepts:1',
            'output': 'extract_prompts'
        },
        params={
            'template': EXTRACT_TEMPLATE
        }
    ))

    await cascade.step(StepLLMCompletion(
        name='extract_design',
        streams={
            'input': 'extract_prompts:1',
            'output': 'raw_design'
        },
        params={
            'model': 'gemma-2-9b-it-exl2-6.0bpw',
            'schema_mode': 'openai-json',
            'sampler': {
                'temperature': 0.3,
                'max_tokens': 512
            }
        }
    ))

    await cascade.step(StepJSONParser(
        name='parse_design',
        streams={
            'input': 'raw_design:1',
            'output': 'designs'
        }
    ))

    await cascade.step(StepExpandTemplate(
        name='expand_image',
        streams={
            'input': 'designs:1',
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
