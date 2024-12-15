import asyncio
import json
from pathlib import Path
from cascade_base import Cascade
from cascade_steps import *

# Load assets
BASIC_WORDS = open('assets/basic.txt').read().splitlines()
ADVANCED_WORDS = open('assets/advanced.txt').read().splitlines()
TECHNIQUES = json.loads(open('assets/world_techniques.json').read())

# Templates
WORLD_TEMPLATE = """Let's engage in an innovative creative brainstorming session using the {{title}} technique. {{summary}}

To spark our imagination, we'll use these random words as inspiration: {{random_words}}

IMPORTANT: DO NOT DIRECTLY MENTION THESE RANDOM WORDS IN YOUR OUTPUT.

We will create the world by exploring the following aspects in detail:

1. Concept: 
   - Explain how the {{title}} technique was specifically applied to generate this world.
   - Describe the key principles or elements of the technique that influenced the world's creation.

2. World Name: 
   - Provide a compelling and meaningful title for the world.
   - Ensure the name reflects the essence or a key aspect of the world.

3. Description:
   - Paint a vivid picture of the world's environment, including its geography, climate, and unique features.
   - Describe the inhabitants, their culture, society, and way of life.
   - Touch on the world's history or origin story if relevant.

4. Sensory Details:
   - Provide specific sensory information about the world (sights, sounds, smells, textures, tastes).
   - Use these details to make the world feel more immersive and tangible.

5. Challenges and Opportunities:
   - Describe some of the main challenges faced by the inhabitants of this world.
   - Highlight unique opportunities or advantages that exist in this world.
      
6. Twist:
   - Introduce an unexpected, interesting, and non-obvious detail about the world.
   - This twist should reveal a hidden depth or complexity to the world, challenging initial perceptions.
   - Explain how this twist impacts the world and its inhabitants.

7. Potential Story Seeds:
   - Suggest 2-3 potential story ideas or conflicts that could arise in this world.
   - These seeds should be unique to the world and stem from its particular characteristics.

Create a distinct and richly detailed example world using this technique, showcasing the versatility of the {{title}} technique.""".strip()

IMAGE_TEMPLATE = '''A movie poster with the text "{{world_name}}" at the bottom. {{description}} {{sensory}}'''

WORLD_SCHEMA = {
    "type": "object",
    "properties": {
        "world_name": {"type": "string", "description": "The World Name"},
        "concept": {"type": "string", "description": "The way in which the concept was applied to create this world"},
        "description": {"type": "string", "description": "Description of the world"},
        "sensory": {"type": "string", "description": "Specific sensory information about the world"},
        "challenges_opportunities": {"type": "string", "description": "Difficulties or opportunities faced by inhabitants of this world"},
        "twist": {"type": "string", "description": "Unique Twist that makes this world interesting"},
        "story_seeds": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Story ideas or conflicts that could arise in this world"
        }
    },
    "required": ["world_name", "concept", "description", "sensory", "challenges_opportunities", "twist", "story_seeds"]
}

async def main():
    # Create pipeline
    cascade = Cascade(project_name='world-builder')
    
    # Define steps
    await cascade.step(StepIdeaSource(
        name='generate_scenario',
        streams={'output': 'vars'},
        params={
            'count': 1,
            'schema': {
                'random_words': {
                    'sample': BASIC_WORDS + ADVANCED_WORDS,
                    'count': 6
                },
                'title': {
                    'sample': [t['title'] for t in TECHNIQUES],
                    'count': 1
                },
                'summary': {
                    'sample': [t['summary'] for t in TECHNIQUES],
                    'count': 1
                }
            }
        }
    ))
    
    await cascade.step(StepExpandTemplate(
        name='expand_world_template',
        streams={
            'input': 'vars:1',
            'output': 'world_prompts'
        },
        params={
            'template': WORLD_TEMPLATE
        }
    ))
    
    await cascade.step(StepLLMCompletion(
        name='generate_world',
        streams={
            'input': 'world_prompts:1',
            'output': 'worlds'
        },
        params={
            'model': 'gpt-4',
            'schema_mode': 'openai-schema',
            'schema_json': WORLD_SCHEMA,
            'sampler': {
                'temperature': 0.7,
                'max_tokens': 2048
            }
        }
    ))
    
    await cascade.step(StepExpandTemplate(
        name='expand_image_template',
        streams={
            'input': 'worlds:1',
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
            'api_url': 'http://localhost:7860',
            'width': 768,
            'height': 768,
            'steps': 30
        }
    ))
    
    await cascade.step(StepJSONSink(
        name='export_json',
        streams={
            'input': 'images:1'
        },
        params={
            'output_dir': 'output/worlds'
        }
    ))
    
    # Run pipeline
    await cascade.run()

if __name__ == '__main__':
    asyncio.run(main())
