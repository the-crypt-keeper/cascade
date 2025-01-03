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

Be specific and detailed in describing 3 potential visual approaches.'''

EXTRACT_TEMPLATE = '''Given the brainstorming output below, extract the list of specific visual design elements for a logo:

<input>
{{input}}
</input>

Format your response as a list of JSON objects with these fields:

[
{
  "concept": "Brief description of the core visual concept",
  "colors": "Specific color palette description",
  "composition": "Description of layout and arrangement"
},
{
  .. same as above ..   
}
]

Reply with only the JSON object.'''

IMAGE_TEMPLATE = '''A minimalist, professional logo design with the text "CASCADE" prominently featured.

Core Concept: {{concept}}
Style: Clean, modern, technical
Colors: {{colors}}
Composition: {{composition}}'''

async def main():
    # Create pipeline
    cascade = Cascade(project_name='logo-gen')
    
    # Generate some random words
    await cascade.step(StepIdeaSource(
        name='generate_scenario',
        streams={'output': 'vars'},
        params={
            'count': 2,
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
    
    # Brainstorm Prompt, Completion
    await cascade.step(StepExpandTemplate(
        name='expand_brainstorm',
        streams={
            'input': 'vars:0',
            'output': 'brainstorm_prompts'
        },
        params={
            'template': BRAINSTORM_TEMPLATE
        }
    ))    
    for brainstorm_model in ['Mistral-large-2407','Meta-Llama-3.1-405B-Instruct']:
        await cascade.step(StepLLMCompletion(
            name='generate_concepts',
            streams={
                'input': 'brainstorm_prompts:0',
                'output': 'raw_concepts'
            },
            params={
                'model': brainstorm_model,
                'sampler': { 'temperature': 1.0, 'max_tokens': 2048 }
            }
        ))
        
    # Extract brainstorm into a JSON list, explode it into designs
    await cascade.step(StepExpandTemplate(
        name='expand_extract',
        streams={
            'input': 'raw_concepts:0',
            'output': 'extract_prompts'
        },
        params={ 'template': EXTRACT_TEMPLATE }
    ))
    await cascade.step(StepLLMCompletion(
        name='extract_design',
        streams={
            'input': 'extract_prompts:0',
            'output': 'raw_design'
        },
        params={
            'model': 'gemma-2-9b-it-exl2-6.0bpw',
            'schema_mode': 'openai-json',
            'parallel': 2,
            'sampler': { 'temperature': 0.3, 'max_tokens': 512 }
        }
    ))
    await cascade.step(StepJSONParser(
        name='parse_design',
        streams={
            'input': 'raw_design:0',
            'output': 'designs'
        },
        params={ 'explode_list': True }
    ))

    # Image prompt and Image completion for each design
    await cascade.step(StepExpandTemplate(
        name='expand_image',
        streams={
            'input': 'designs:0',
            'output': 'image_prompts'
        },
        params={'template': IMAGE_TEMPLATE }
    ))    
    # await cascade.step(StepConsoleSink(name='console_sink', streams={'input': 'image_prompts:0'}))
    for image_model in ['flux1-schnell-q4_k','flux-hyp8-Q8_0']:
        await cascade.step(StepText2Image(
            name='generate_image',
            streams={'input': 'image_prompts:0', 'output': 'images'},
            params={
                'width': 512,
                'height': 512,
                'n': 2,
                'model': image_model
            }
        ))
    
    # Output .png and .json
    await cascade.step(StepJSONSink(
        name='export_json',
        streams={ 'input': 'images:0' },
        params={ 'output_dir': 'output/logos' }
    ))
    
    # Run pipeline
    await cascade.run()

if __name__ == '__main__':
    asyncio.run(main())
