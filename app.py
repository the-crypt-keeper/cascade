import streamlit as st
import sys
from pathlib import Path
import json
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from cascade_base import Cascade, Message

def parse_step(step: str) -> Tuple[str, Dict[str, str]]:
    """Parse a step into name and parameters"""
    if ':' in step:
        name, param_str = step.split(':', 1)
        params = dict(p.split('=') for p in param_str.split(','))
        return name, params
    return step, {}

def parse_cascade_id(cascade_id: str) -> List[Tuple[str, Dict[str, str]]]:
    """Split cascade ID into step components"""
    if not cascade_id:
        return []
    
    steps = []
    for step in cascade_id.split('/'):
        # Skip empty steps and merge nodes
        if not step or step.startswith('['):
            continue
        steps.append(parse_step(step))
    return steps

def analyze_step_variations(messages: List[Message]) -> Dict[str, Set[str]]:
    """Find all unique step names and their parameter variations"""
    step_params: Dict[str, Set[str]] = {}
    
    for msg in messages:
        steps = parse_cascade_id(msg.cascade_id)
        for name, params in steps:
            if name not in step_params:
                step_params[name] = set()
            if params:
                param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items()))
                step_params[name].add(param_str)
            else:
                step_params[name].add("")
                
    return step_params

def format_step(name: str, params: Dict[str, str]) -> str:
    """Format step name and parameters for display"""
    if params:
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"{name} ({param_str})"
    return name

def get_step_suggestions(step_params: Dict[str, Set[str]]) -> Tuple[List[str], List[str]]:
    """Suggest split and compare dimensions based on parameter variations"""
    varying_steps = []
    constant_steps = []
    all_steps = list(step_params.keys())
    
    for step_name, param_variations in step_params.items():
        if len(param_variations) > 1:
            varying_steps.append(step_name)
        else:
            constant_steps.append(step_name)
    
    if varying_steps:
        # If we have varying steps, use last as compare and others as splits
        splits = varying_steps[:-1]
        compares = varying_steps[-1:]
    else:
        # If no varying steps, use first step as split and last as compare
        splits = [all_steps[0]] if all_steps else []
        compares = []
    
    # Always include last step as compare if not already included
    last_step = all_steps[-1] if all_steps else None
    if last_step and last_step not in compares:
        compares.append(last_step)
    
    return splits, compares

def group_by_splits(messages: List[Message], split_steps: List[str], compare_steps: List[str]) -> Dict:
    """Group messages by split dimensions"""
    groups = defaultdict(list)
    
    for msg in messages:
        components = {name: params for name, params in parse_cascade_id(msg.cascade_id)}
        
        # Build split key
        if split_steps:
            split_components = []
            for step in split_steps:
                params = components.get(step, {})
                param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items())) if params else ""
                split_components.append((step, param_str))
            split_key = tuple(split_components)
        else:
            split_key = ('all',)
            
        # Build compare key
        if compare_steps:
            compare_components = []
            for step in compare_steps:
                params = components.get(step, {})
                param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items())) if params else ""
                compare_components.append((step, param_str))
            compare_key = tuple(compare_components)
        else:
            compare_key = ('value',)
        
        # Group messages
        groups[split_key].append((compare_key, msg))
        
    return groups

def main():
    st.set_page_config(layout="wide")
    st.title("Cascade Database Explorer")
    
    # Get project name from command line
    if len(sys.argv) != 2:
        st.error("Please provide project name as command line argument")
        return
        
    project_name = sys.argv[1]
    
    # Initialize Cascade
    cascade = Cascade(project_name)
    
    # Get available streams
    streams = asyncio.run(cascade.storage.get_all_streams())
    
    if not streams:
        st.warning("No streams found in database")
        return
        
    # Stream selection
    selected_stream = st.selectbox("Select Stream", streams)
    
    # Get messages for selected stream
    messages = asyncio.run(cascade.storage.get_all_messages(selected_stream))
    
    if not messages:
        st.warning(f"No messages found in stream: {selected_stream}")
        return
        
    # Analyze step variations
    step_params = analyze_step_variations(messages)
    step_names = list(step_params.keys())
    
    # Get suggested splits/compares
    default_splits, default_compares = get_step_suggestions(step_params)
    
    # UI for selecting split/compare dimensions
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Split Dimensions")
        splits = st.multiselect(
            "Select split dimensions",
            step_names,
            default=default_splits,
            help="Steps with varying parameters to split on"
        )
        
    with col2:
        st.subheader("Compare Dimensions")
        compares = st.multiselect(
            "Select compare dimensions",
            step_names,
            default=default_compares,
            help="Steps with varying parameters to compare"
        )
    
    # Validate dimensions
    if not splits or not compares:
        st.error("Please select both split and compare dimensions to analyze the results.")
        return
        
    # Group messages
    groups = group_by_splits(messages, splits, compares)
    
    # Display groups
    for split_key, group in groups.items():
        # Format split key for display
        split_display = []
        for name, param_str in split_key:
            split_display.append(f"{name} ({param_str})" if param_str else name)
        st.header(f"{' / '.join(split_display)}")
        
        # Organize by compare keys
        columns = defaultdict(dict)
        for compare_key, msg in group:
            # Unroll cascade
            history = asyncio.run(cascade.manager.unroll(msg))
            
            # Store in columns
            columns[compare_key] = history
        
        # Create columns for each compare key
        cols = st.columns(max(1, len(columns)))
        
        for i, (compare_key, history) in enumerate(columns.items()):
            with cols[i]:
                # Format compare key for display
                compare_display = []
                for name, param_str in compare_key:
                    compare_display.append(f"{name} ({param_str})" if param_str else name)
                st.subheader(f"{' / '.join(compare_display)}")
                
                # Get steps from compare dimensions
                compare_steps = set(name for name, _ in compare_key)
                
                # Display compare dimension values first
                for step, data in history.items():
                    if step in compare_steps:
                        st.write(f"**{step}:**")
                        if isinstance(data, dict) and 'image' in data:
                            # Handle base64 image data
                            import base64
                            from io import BytesIO
                            try:
                                image_bytes = base64.b64decode(data['image'])
                                st.image(image_bytes)
                                    
                                # Show other metadata
                                other_data = {k:v for k,v in data.items() if k != 'image'}
                                if other_data:
                                    st.json(other_data)
                            except Exception as e:
                                st.error(f"Failed to decode image: {e}")
                        elif isinstance(data, (dict, list)):
                            # Show JSON data
                            st.json(data)
                        else:
                            # Show string/primitive data
                            st.write(data)
                
                # Put other history items in expander
                other_history = {k:v for k,v in history.items() if k not in compare_steps}
                if other_history:
                    with st.expander("More..."):
                        for step, data in other_history.items():
                            st.write(f"**{step}:**")
                            if isinstance(data, dict) and 'image' in data:
                                # Handle base64 image data
                                import base64
                                from io import BytesIO
                                try:
                                    image_bytes = base64.b64decode(data['image'])
                                    st.image(image_bytes)
                                    
                                    # Show other metadata
                                    other_data = {k:v for k,v in data.items() if k != 'image'}
                                    if other_data:
                                        st.json(other_data)
                                except Exception as e:
                                    st.error(f"Failed to decode image: {e}")
                            elif isinstance(data, (dict, list)):
                                # Show JSON data
                                st.json(data)
                            else:
                                # Show string/primitive data
                                st.write(data)

if __name__ == "__main__":
    import asyncio
    main()
