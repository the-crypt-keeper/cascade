
# Cascade

Cascade is a streaming pipeline system for complex content generation tasks. It enables the construction of idempotent, parallel processing pipelines through a simple YAML configuration format.

## Key Features

- **Streaming Architecture**: Steps process items asynchronously through named streams
- **Idempotent Processing**: Work is tracked through cascade IDs, ensuring each item is processed exactly once
- **Fair Load Balancing**: Multiple consumers can process items from a stream with configurable weights
- **Simple Configuration**: Pipelines are defined in YAML with asset loading and parameter resolution
- **Flexible Step Types**: Source, Transform, and Sink steps for different processing needs

## How It Works

### Cascade IDs

The core concept in Cascade is the cascade ID, which tracks the lineage of each piece of data through the pipeline. Cascade IDs are built up as data flows through steps:

```
source_step:count=0                     # Initial generation
source_step:count=0/transform_step      # After transformation
[branch1:count=0|branch2:count=1]/merge # Merged from multiple sources
```

This ID system ensures idempotency and enables tracing of data lineage.

### Streams and Steps

Data flows through the pipeline via named streams. Steps can:
- Produce data into streams (Source steps)
- Consume and transform data (Transform steps)
- Consume and export data (Sink steps)

Multiple steps can consume from the same stream with fair load balancing based on cascade ID hashing.

### Example Usage

See [example-simple.py](example-simple.py) and [code-challenge.py](code-challenge.py) for complete examples of building pipelines using the Python API.

## Architecture

- `cascade_base.py`
    - **Cascade**: Main pipeline class for constructing and running pipelines
    - **Stream**: Handles message passing between steps with fair load balancing
    - **CascadeManager**: Coordinates steps and streams, tracks pipeline completion
    - **SQLiteStorage**: Provides persistent storage and idempotency checking
- `cascade_steps.py`: Provides the core step implementations

### Source Steps

Source steps generate initial data into the pipeline. They have no input streams and one or more output streams.

#### StepIdeaSource
Generates data by sampling from configured sources according to a schema.

Parameters:
- **count**: Number of scenarios to generate (default: 1)
- **schema**: Dictionary defining data generation rules
  - Each key defines a field to generate
  - Values can be:
    - **sample**: List to sample from
    - **count**: Number of items to sample
    - **always_array**: Always return as array even if count=1
    - **constant**: Fixed value to use

Example:
```python
await cascade.step(StepIdeaSource(
    name='generate_scenario',
    streams={'output': 'vars'},
    params={
        'count': 5,
        'schema': {
            'random_words': {
                'sample': word_list,
                'count': 3,
                'always_array': True
            },
            'constant_value': {
                'constant': 'fixed string'
            }
        }
    }
))
```

### Transform Steps

Transform steps process input data and produce transformed output. They support parallel processing through the `parallel` parameter.

#### StepExpandTemplate
Expands Jinja2 templates using input data.

Parameters:
- **template**: Jinja2 template string to expand

Example:
```python
await cascade.step(StepExpandTemplate(
    name='expand_template',
    streams={
        'input': 'vars:1',
        'output': 'prompts'
    },
    params={
        'template': "Template using {{variable}}"
    }
))
```

#### StepLLMCompletion
Processes text through language models.

Parameters:
- **model**: Name of model to use
- **tokenizer**: Optional tokenizer name for special formatting
- **parallel**: Number of parallel workers (default: 1)
- **sampler**: Dictionary of sampling parameters
  - **temperature**: Sampling temperature
  - **max_tokens**: Maximum tokens to generate
  - Additional model-specific parameters

Example:
```python
await cascade.step(StepLLMCompletion(
    name='generate',
    streams={
        'input': 'prompts:1',
        'output': 'responses'
    },
    params={
        'model': 'gemma-2b',
        'tokenizer': 'internal:vicuna',
        'parallel': 2,
        'sampler': {
            'temperature': 0.7,
            'max_tokens': 1024
        }
    }
))
```

#### StepJSONParser
Parses and transforms JSON data.

Parameters:
- **first_key**: Extract value of first key only
- **explode_list**: Split list field into separate outputs
- **explode_keys**: List of keys to output separately

Example:
```python
await cascade.step(StepJSONParser(
    name='parse_json',
    streams={
        'input': 'responses:1',
        'output': 'parsed'
    },
    params={
        'first_key': True,
        'explode_list': 'items',
        'explode_keys': ['key1', 'key2']
    }
))
```

#### StepText2Image
Generates images from text descriptions using Stable Diffusion.

Parameters:
- **api_url**: URL of Stable Diffusion API
- **width**: Image width (default: 512)
- **height**: Image height (default: 512)
- **steps**: Number of diffusion steps (default: 20)

Example:
```python
await cascade.step(StepText2Image(
    name='generate_image',
    streams={
        'input': 'prompts:1',
        'output': 'images'
    },
    params={
        'api_url': 'http://localhost:7860',
        'width': 768,
        'height': 768,
        'steps': 30
    }
))
```

### Sink Steps

Sink steps consume data from the pipeline and perform final processing. They have one or more input streams but no outputs.

#### StepJSONSink
Exports complete cascade histories to JSON files.

Parameters:
- **output_dir**: Directory to write JSON files (default: '.')

Example:
```python
await cascade.step(StepJSONSink(
    name='export_json',
    streams={
        'input': 'final_output:1'
    },
    params={
        'output_dir': 'output/results'
    }
))
```

#### StepConsoleSink
Outputs messages directly to console.

Parameters: None

Example:
```python
await cascade.step(StepConsoleSink(
    name='console',
    streams={
        'input': 'responses:1'
    }
))
```

## Installation

Cascade uses `uv` for dependency management. To set up:

```bash
# Install dependencies from lock file
uv sync
```

## Usage

1. Create a Python script that defines your pipeline
2. (optional) Implement any custom steps required
3. Run the pipeline:
```bash
uv run your_pipeline.py
```

## Step Implementation

Cascade provides three base step types that can be extended to create custom processing steps. All steps support common configuration:

- **name**: Unique identifier for the step
- **streams**: Input/output stream configuration  
- **params**: Step-specific parameters

### Source Steps

Source steps generate initial data into the pipeline. They have no input streams and one or more output streams.

Example usage:
```python
await cascade.step(StepIdeaSource(
    name='generate_scenario',
    streams={'output': 'vars'},
    params={
        'count': 5,
        'schema': {
            'random_words': {
                'sample': word_list,
                'count': 3
            },
            'technique': {
                'sample': techniques,
                'count': 1
            }
        }
    }
))
```

### Transform Steps 

Transform steps process input data and produce transformed output. They support parallel processing through the `parallel` parameter.

Example template expansion:
```python
await cascade.step(StepExpandTemplate(
    name='expand_template',
    streams={
        'input': 'vars:1',
        'output': 'prompts'
    },
    params={
        'template': "Template using {{variable}}"
    }
))
```

Example LLM completion:
```python
await cascade.step(StepLLMCompletion(
    name='generate',
    streams={
        'input': 'prompts:1', 
        'output': 'responses'
    },
    params={
        'model': 'gemma-2b',
        'parallel': 2,
        'sampler': {
            'temperature': 0.7,
            'max_tokens': 1024
        }
    }
))
```

Example JSON parsing:
```python
await cascade.step(StepJSONParser(
    name='parse_json',
    streams={
        'input': 'responses:1',
        'output': 'parsed'
    },
    params={
        'first_key': True,  # Extract first key's value
        'explode_list': 'items',  # Split list into separate outputs
        'explode_keys': ['key1', 'key2']  # Output keys separately
    }
))
```

### Sink Steps

Sink steps consume data from the pipeline and perform final processing. They have one or more input streams but no outputs.

Example JSON export:
```python
await cascade.step(StepJSONSink(
    name='export_json',
    streams={
        'input': 'final_output:1'
    },
    params={
        'output_dir': 'output/results'
    }
))
```

Output format:
```json
{
  "cascade_id": "source:count=0/transform",
  "history": {
    "source": {"generated": "data"},
    "transform": "processed result"
  }
}
```
