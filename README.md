
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

### Configuration Example

See [example-simple.yaml](example-simple.yaml) for a complete example of a simple pipeline that generates some seeds, expands a template and performs and LLM completion.

## Architecture

- `cascade_base.py`
    - **Stream**: Handles message passing between steps with fair load balancing
    - **CascadeManager**: Coordinates steps and streams, tracks pipeline completion
    - **CascadeLoader**: Configuration and asset loading and parameter resolution
    - **SQLiteStorage**: Provides persistent storage and idempotency checking
- `cascade_steps.py`
    - **Step Classes**: Processing step implementations
- `main.py`    
    - **Cascade**: System entrypoint to load a configuration and run the pipeline.

## Installation

Cascade uses `uv` for dependency management. To set up:

```bash
# Install dependencies from lock file
uv sync

# Run pipeline
uv run main.py example-simple.yaml
```

## Step Implementation

Cascade currently provides three core step types:

### StepIdeaSource (SourceStep)

Generates initial data by sampling from configured sources:

```yaml
steps:
  generate_scenario:
    class: cascade_steps.StepIdeaSource
    streams:
      output: vars
    params:
      count: 5
      schema:
        random_basic_words: 
            sample: $assets.basic_words
            count: 3
        random_advanced_words:
            sample: $assets.advanced_words
            count: 3
        technique: 
            sample: $assets.world_techniques
            count: 1
```

This will produce output like:
```python
{
    'random_basic_words': ['cat', 'dog', 'house'],
    'random_advanced_words': ['ephemeral', 'serendipity', 'mellifluous'],
    'technique': {'title': 'Historical Analog Approach', ...}  # Single item since count=1
}
```

### StepExpandTemplate (TransformStep)

Expands a Jinja2 template using input data:

```yaml
steps:
  expand_template:
    class: cascade_steps.StepExpandTemplate
    streams:
      input: vars:1
      output: prompts
    params:
      template: |-
        Let's create something using {{technique.title}}.
        Our inspiration words are: {{random_basic_words|join(', ')}}.
```

The template has access to all keys from the input dictionary and standard Jinja2 filters.

### StepLLMCompletion (TransformStep)

Processes input through a language model:

```yaml
steps:
  generate_response:
    class: cascade_steps.StepLLMCompletion
    streams:
      input: prompts:1
      output: responses
    params:
      model: "mistral"  # Required: LLM model to use
      tokenizer: "mistral"  # Optional: tokenizer name
      sampler:  # Optional sampling parameters
        temperature: 0.7
        max_tokens: 1024
```

The step supports:
- Custom model selection
- Optional tokenizer configuration
- Configurable sampling parameters
- Automatic chat template application when using tokenizers

### StepJSONParser (Step)

Parses JSON from input text and provides flexible output options:

```yaml
steps:
  parse_json:
    class: cascade_steps.StepJSONParser
    streams:
      input: responses
      output: parsed
    params:
      first_key: true  # Optional: return only the first key's value
      explode_list: "items"  # Optional: split list field into separate outputs
      explode_keys: ["field1", "field2"]  # Optional: output specific keys separately
```

The step supports several parsing modes:

- **Basic JSON parsing**: By default, parses the first valid JSON object found in the input text
- **First Key Extraction**: With `first_key: true`, returns only the value of the first key in the JSON object
- **List Explosion**: With `explode_list: "field_name"`, splits a list field into separate output messages
- **Key Explosion**: With `explode_keys: ["key1", "key2"]`, outputs specified fields as separate messages

Example input/output:

```python
# Input text containing JSON
'''Some text before {"items": ["a", "b", "c"], "other": "data"} and after'''

# With explode_list: "items" produces three outputs:
"a"  # cascade_id: input_step:count=0/parse_json:index=0
"b"  # cascade_id: input_step:count=0/parse_json:index=1
"c"  # cascade_id: input_step:count=0/parse_json:index=2
```

### StepJSONSink (SinkStep)

Exports the complete history of a cascade to a JSON file:

```yaml
steps:
  export_json:
    class: cascade_steps.StepJSONSink
    streams:
      input: prompts:1
    params:
      output_dir: output/scenarios
```

Creates files named with MD5 hashes of cascade IDs containing:
```json
{
  "cascade_id": "generate_scenario:count=0/expand_template",
  "history": {
    "generate_scenario": {
      "random_basic_words": ["cat", "dog", "house"],
      "random_advanced_words": ["ephemeral", "serendipity", "mellifluous"],
      "technique": {"title": "Historical Analog Approach", ...}
    },
    "expand_template": "Let's create something using Historical Analog Approach..."
  }
}
```

## Usage

1. Define your pipeline in YAML
2. Implement your custom steps
3. Run the pipeline:
```bash
uv run main.py pipeline.yaml
```
