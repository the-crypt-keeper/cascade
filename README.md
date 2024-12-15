# Cascade

Cascade is a Python asyncio-based streaming pipeline system for content generation tasks. It enables the construction of idempotent, parallel processing pipelines through a simple async python API.

## Key Features

- **Simple API**: Pipelines are defined using Python.
- **Streaming Architecture**: Steps process items asynchronously through named streams
- **Flexible Step Types**: Source, Transform, and Sink steps for different processing needs
- **Idempotent Processing**: Work is tracked through cascade IDs, ensuring each item is processed exactly once
- **Load Balancing**: Multiple consumers can process items from a stream with configurable weights
- **Parallel Processing**: Multiple workers can process items from a stream in parallel.

## How It Works

### Streams and Steps

In the Cascade pipeline, data flows through Steps via named Streams.

Steps can:

- Produce data (Source steps)
- Consume and transform data (Transform steps)
- Consume and export data (Sink steps)

Multiple Steps can consume from the same Stream with configurable load balancing strategies.

### Cascade IDs

The core concept in Cascade is the cascade ID, which tracks the lineage of each piece of data through the pipeline. Cascade IDs are built up as data flows through steps:

```
source_step:count=0                     # Initial generation
source_step:count=0/transform_step      # After transformation
[branch1:count=0|branch2:count=1]/merge # Merged from multiple sources
```

This ID system ensures idempotency and enables tracing of data lineage.

## Usage

1. Create a Python script that defines your pipeline
2. Run the pipeline:
```bash
uv run your_pipeline.py
```

See [example-simple.py](example-simple.py) and [code-challenge.py](code-challenge.py) for complete examples of building pipelines using the Python API.

## Architecture

- `cascade_base.py`
    - **Cascade**: Main pipeline class for constructing and running pipelines
    - **Stream**: Handles message passing between steps with fair load balancing
    - **CascadeManager**: Coordinates steps and streams, tracks pipeline completion
    - **SQLiteStorage**: Provides persistent storage and idempotency checking
- `cascade_steps.py`: Provides the core step implementations:
    - Source Steps:
        - [StepIdeaSource](#stepideasource): Generates data by sampling from configured sources
    - Transform Steps:
        - [StepExpandTemplate](#stepexpandtemplate): Expands Jinja2 templates
        - [StepLLMCompletion](#stepllmcompletion): Processes text through language models
        - [StepJSONParser](#stepjsonparser): Parses and transforms JSON data
        - [StepText2Image](#steptext2image): Generates images from text descriptions
    - Sink Steps:
        - [StepJSONSink](#stepjsonsink): Exports cascade histories to JSON files
        - [StepConsoleSink](#stepconsolesink): Outputs messages to console

### Source Steps

Source steps generate initial data into the pipeline. They have no input streams and one or more output streams.

#### StepIdeaSource
Generates data by sampling from configured sources according to a schema.

Streams:
- **output**: Produces generated data samples

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

Streams:
- **input**: Receives data for template variables
- **output**: Produces expanded template text

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

Streams:
- **input**: Receives prompts for completion
- **output**: Produces model responses

Parameters:
- **model**: *Required* Name of model to use
- **tokenizer**: Optional tokenizer name to use text-completion instead of chat-completion endpoint
- **sampler**: Dictionary of sampling parameters
  - **temperature**: Sampling temperature
  - **max_tokens**: Maximum tokens to generate
  - Additional model-specific parameters
- **parallel**: Number of parallel workers (default: 1)
- **schema_mode**: JSON generation mode (default: "none")
  - **none**: No structured output
  - **openai-schema**: Use OpenAI function schema
  - **openai-json**: Force JSON object output
  - **vllm**: Use vLLM guided JSON
  - **llama**: Use Llama JSON schema
- **schema_json**: JSON schema for structured generation modes

Example:
```python
await cascade.step(StepLLMCompletion(
    name='generate',
    streams={
        'input': 'prompts:1',
        'output': 'responses'
    },
    params={
        'model': 'gpt-4',
        'parallel': 2,
        'schema_mode': 'openai-schema',
        'schema_json': {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name", "age"]
        },
        'sampler': {
            'temperature': 0.7,
            'max_tokens': 1024
        }
    }
))
```

#### StepJSONParser
Parses and transforms JSON data.

Streams:
- **input**: Receives JSON text to parse
- **output**: Produces parsed JSON objects

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

Streams:
- **input**: Receives text prompts
- **output**: Produces generated images

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

Streams:
- **input**: Receives data to export as JSON

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

#### StepConsoleSink
Outputs messages directly to console.

Streams:
- **input**: Receives messages to print

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
