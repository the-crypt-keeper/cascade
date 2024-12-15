import asyncio
from cascade_main import Cascade
from cascade_steps import *

# Load assets
BASIC_WORDS = open('assets/basic.txt').readlines()
ADVANCED_WORDS = open('assets/advanced.txt').readlines()
STORY_TEMPLATE = '''
Let's engage in a short story creative writing session.

To spark our imagination, we'll use these random words as inspiration: {{random_basic_words|join(', ')}}, {{random_advanced_words|join(', ')}}

IMPORTANT: DO NOT DIRECTLY MENTION THAT YOU USED THESE RANDOM WORDS IN YOUR OUTPUT.

The short story should have a title and be 3 paragraphs long.
'''.strip()

async def main():
    # Create pipeline
    cascade = Cascade(config_path=Path('example-simple'))
    
    # Define steps
    await cascade.step(StepIdeaSource(
        name='generate_scenario',
        streams={'output': 'vars'},
        params={
            'count': 1,
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
        name='expand_template',
        streams={
            'input': 'vars:1',
            'output': 'prompts'
        },
        params={
            'template': STORY_TEMPLATE
        }
    ))
    
    await cascade.step(StepLLMCompletion(
        name='generate_response',
        streams={
            'input': 'prompts:1',
            'output': 'responses'
        },
        params={
            'model': 'gemma-2-9b-it-exl2-6.0bpw',
            'sampler': {
                'temperature': 0.7,
                'max_tokens': 2048,
                'n': 2
            }
        }
    ))
    
    await cascade.step(StepConsoleSink(
        name='console',
        streams={
            'input': 'responses:1'
        },
        params={}
    ))
    
    # Run pipeline
    await cascade.run()

if __name__ == '__main__':
    asyncio.run(main())
