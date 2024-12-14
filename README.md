
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
- `cascade_main.py`
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

Cascade provides three base step types that can be extended to create custom processing steps. All steps support common configuration options:

- **name**: Unique identifier for the step
- **streams**: Input/output stream configuration
- **params**: Step-specific parameters

### Source Steps

Source steps generate initial data into the pipeline. They have no input streams and one or more output streams.

Base configuration:
```yaml
steps:
  my_source:
    class: cascade_steps.MySourceStep
    streams:
      output: output_stream
    params:
      count: 5  # Number of items to generate
```

Available implementations:

#### StepIdeaSource
Generates data by sampling from configured sources:

```yaml
steps:
  generate_scenario:
    class: cascade_steps.StepIdeaSource
    streams:
      output: vars
    params:
      count: 5
      schema:
        random_words: 
          sample: $assets.word_list
          count: 3
        technique: 
          sample: $assets.techniques
          count: 1
```

### Transform Steps

Transform steps process input data and produce transformed output. They support parallel processing through the `parallel` parameter.

Base configuration:
```yaml
steps:
  my_transform:
    class: cascade_steps.MyTransformStep
    streams:
      input: input_stream:1  # :1 specifies consumer weight
      output: output_stream
    params:
      parallel: 2  # Number of parallel workers
```

Available implementations:

#### StepExpandTemplate
Expands Jinja2 templates using input data:

```yaml
steps:
  expand_template:
    class: cascade_steps.StepExpandTemplate
    streams:
      input: vars:1
      output: prompts
    params:
      template: "Template using {{variable}}"
      parallel: 2
```

#### StepLLMCompletion
Processes text through language models:

```yaml
steps:
  generate:
    class: cascade_steps.StepLLMCompletion
    streams:
      input: prompts:1
      output: responses
    params:
      model: "mistral"
      tokenizer: "mistral"  # Optional
      parallel: 2
      sampler:
        temperature: 0.7
        max_tokens: 1024
```

#### StepJSONParser
Parses and transforms JSON data:

```yaml
steps:
  parse_json:
    class: cascade_steps.StepJSONParser
    streams:
      input: responses:1
      output: parsed
    params:
      first_key: true  # Extract first key's value
      explode_list: "items"  # Split list into separate outputs
      explode_keys: ["key1", "key2"]  # Output keys separately
      parallel: 2
```

### Sink Steps

Sink steps consume data from the pipeline and perform final processing. They have one or more input streams but no outputs.

Base configuration:
```yaml
steps:
  my_sink:
    class: cascade_steps.MySinkStep
    streams:
      input: input_stream:1
    params:
      output_dir: "output/"
```

Available implementations:

#### StepJSONSink
Exports complete cascade histories to JSON files:

```yaml
steps:
  export_json:
    class: cascade_steps.StepJSONSink
    streams:
      input: final_output:1
    params:
      output_dir: output/results
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

## Usage

1. Define your pipeline in YAML
2. Implement your custom steps
3. Run the pipeline:
```bash
uv run main.py pipeline.yaml
```
