import asyncio
from cascade_base import Cascade
from cascade_steps import *
from pathlib import Path

# Load assets
BASIC_WORDS = open('assets/basic.txt').read().splitlines()
ADVANCED_WORDS = open('assets/advanced.txt').read().splitlines()

# Templates
IDEA_TEMPLATE = '''
You are tasked with brainstorming a list of programming challenge tasks suitable for senior-level developers. These challenges should be complex, requiring advanced knowledge and skills in various areas of computer science and software engineering.

Guidelines for generating challenge ideas:
- Focus on tasks that require deep understanding of algorithms, data structures, and system design
- Include challenges that test problem-solving skills, optimization abilities, and architectural thinking
- Vary the difficulty level, but ensure all challenges are appropriate for senior developers
- Cover a wide range of topics in computer science and software engineering

Your output should be a numbered list of exactly 3 challenge tasks. Each task should have:
1. A concise title
2. A brief description (1-2 sentences)
3. Key concepts or skills tested

Examples of challenge categories and specific tasks:
1. Advanced Algorithms: Implement a parallel merge sort algorithm
2. Distributed Systems: Design a distributed cache with consistency guarantees
3. Language Design: Create a basic interpreter for a custom programming language
4. Machine Learning: Implement a neural network from scratch without using ML libraries
5. Operating Systems: Write a simple scheduler for a multi-threaded operating system

First, use a <scratchpad></scratchpad> field to free-form brainstorm ideas before designing the challenges, using the following random words as entropy: {{random_basic_words|join(', ')}}, {{random_advanced_words|join(', ')}}. Consider various areas of computer science and software engineering that would challenge a senior developer. Explore a diverse range of concepts.

Then, provide your final response in JSON format:

```json
{
    "challenge_0_title": "<first challenge title>",
    "challenge_0_description": "<first challenge description>",
    "challenge_0_concepts": "<concepts covered by the first challenge>",
    "challenge_1_title": "<second challenge title>",
    "challenge_1_description": "<second challenge description>",
    "challenge_1_concepts": "<concepts covered by the second challenge>",
    "challenge_2_title": "<third challenge title>",
    "challenge_2_description": "<third challenge description>",
    "challenge_2_concepts": "<concepts covered by the third challenge>"
}
```

Make SURE the JSON structure is VALID, all values are STRINGS and every { matches a }.
'''.strip()

TASK_TEMPLATE = '''
You will be given a JSON object containing information about three programming challenges.

Your task is to think step-by-step to analyze these challenges, select the most appropriate one to be represented as a single function, design that function, and create test cases for it. Follow these steps:

1. Consider the following brainstorm ideas for programming challenges:

Challenge 0:
Title: {{challenge_0_title}}
Description: {{challenge_0_description}}
Concepts: {{challenge_0_concepts}}

Challenge 1:
Title: {{challenge_1_title}}
Description: {{challenge_1_description}}
Concepts: {{challenge_1_concepts}}

Challenge 2:
Title: {{challenge_2_title}}
Description: {{challenge_2_description}}
Concepts: {{challenge_2_concepts}}

2. Analyze the three challenges and select the one that is most appropriate to be represented as a single function that takes only simple data types (int, str, float, list, dict) as inputs and outputs. Consider the complexity of the challenge (prefer higher complexity) and how well it can be encapsulated in a single function.

3. For the selected challenge, design (but do not implement) the function that best represents its core concepts while adhereing to the restrictions above. Describe the function's operations, inputs, and outputs in detail. Ensure that the function only uses simple data types for its inputs and outputs.

4. Generate 7-10 test cases for this function. Include both typical use cases and potential error conditions. Each test case should specify the input(s) and the expected output or behavior.

5. Present your final result in a YAML block, formatted as follows:

```yaml
ChallengeName:
    Signature: "function_name(param1, param2, ...)"
    Input: "Description of input parameters"
    Output: "Description of the function's output"
    Description: "A DETAILED description of the function's purpose and expected methods of operation"
    Checks:
        test_case_1:
            assert: function_call(args)
            eq: expected_output
        test_case_2:
            assert: function_call(args)
            eq: expected_output
        # ... (include all 7-10 test cases)
```

Ensure that your YAML block includes all necessary information about the function and all 7-10 test cases. Use appropriate indentation and formatting for the YAML structure.

Remember to think step-by-step, starting from step 1!
'''.strip()

async def main():
    # Create pipeline
    cascade = Cascade(project_name='code-challenge')
    
    # Define steps
    await cascade.step(StepIdeaSource(
        name='generate_scenario',
        streams={'output': 'vars'},
        params={
            'count': 4,
            'schema': {
                'random_basic_words': {
                    'sample': BASIC_WORDS,
                    'count': 3
                },
                'random_advanced_words': {
                    'sample': ADVANCED_WORDS,
                    'count': 7
                }
            }
        }
    ))
    
    await cascade.step(StepExpandTemplate(
        name='expand_idea_template',
        streams={
            'input': 'vars:1',
            'output': 'idea_prompts'
        },
        params={
            'template': IDEA_TEMPLATE
        }
    ))
    
    await cascade.step(StepLLMCompletion(
        name='generate_ideas',
        streams={
            'input': 'idea_prompts:1',
            'output': 'raw_ideas'
        },
        params={
            'model': 'gemma-2-9b-it-exl2-6.0bpw',
            'schema_mode': 'openai-json',
            'parallel': 2,
            'sampler': {
                'temperature': 0.7,
                'max_tokens': 2048
            }
        }
    ))
    
    await cascade.step(StepJSONParser(
        name='parse_ideas',
        streams={
            'input': 'raw_ideas:1',
            'output': 'parsed_ideas'
        }
    ))
    
    await cascade.step(StepExpandTemplate(
        name='expand_task_template',
        streams={
            'input': 'parsed_ideas:1',
            'output': 'task_prompts'
        },
        params={
            'template': TASK_TEMPLATE
        }
    ))
    
    await cascade.step(StepLLMCompletion(
        name='generate_task',
        streams={
            'input': 'task_prompts:1',
            'output': 'tasks'
        },
        params={
            'parallel': 2,
            'model': 'Cohere-command-r-plus',
            'sampler': {
                'temperature': 0.7,
                'max_tokens': 4096
            }
        }
    ))
    
    await cascade.step(StepJSONSink(
        name='export_json',
        streams={
            'input': 'tasks:1'
        },
        params={
            'output_dir': 'output/challenges'
        }
    ))
    
    # Run pipeline
    await cascade.run()

if __name__ == '__main__':
    asyncio.run(main())
