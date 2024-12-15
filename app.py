import streamlit as st
import sys
from pathlib import Path
import json
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from cascade_base import Cascade, Message

def parse_step_component(component: str) -> Tuple[str, Dict[str, str]]:
    """Parse a step component into name and parameters"""
    if ':' in component:
        name, param_str = component.split(':', 1)
        params = dict(p.split('=') for p in param_str.split(','))
        return name, params
    return component, {}

def parse_cascade_id(cascade_id: str) -> List[Tuple[str, Dict[str, str]]]:
    """Split cascade ID into components, handling merge nodes and parameters"""
    components = []
    current = ""
    
    i = 0
    while i < len(cascade_id):
        if cascade_id[i] == '[':
            # Skip merge nodes
            merge_end = cascade_id.index(']', i)
            i = merge_end + 1
            if i < len(cascade_id) and cascade_id[i] == '/':
                i += 1
        else:
            if cascade_id[i] == '/':
                if current:
                    components.append(parse_step_component(current))
                    current = ""
            else:
                current += cascade_id[i]
            i += 1
            
    if current:
        components.append(parse_step_component(current))
        
    return components

def format_step(name: str, params: Dict[str, str]) -> str:
    """Format step name and parameters for display"""
    if params:
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"{name} ({param_str})"
    return name

def analyze_cascade_paths(messages: List[Message]) -> Tuple[List[str], List[str], List[str]]:
    """Analyze cascade paths to identify common and unique components"""
    # Get all unique values for each position
    position_values: Dict[int, Set[str]] = defaultdict(set)
    
    # Parse all cascade IDs
    parsed_paths = [parse_cascade_id(msg.cascade_id) for msg in messages]
    
    # Find unique values at each position
    for path in parsed_paths:
        for i, (name, params) in enumerate(path):
            # Convert to hashable format (name + sorted param string)
            param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items())) if params else ""
            hashable = (name, param_str) if param_str else name
            position_values[i].add(hashable)
            
    # Categorize positions
    common = []  # Same value in all paths
    unique = []  # Different values across paths
    
    max_len = max(len(path) for path in parsed_paths)
    
    for i in range(max_len):
        if len(position_values[i]) == 1:
            # Convert back to name, params format
            value = list(position_values[i])[0]
            if isinstance(value, tuple):
                name, param_str = value
                params = dict(p.split('=') for p in param_str.split(',')) if param_str else {}
                common.append((name, params))
            else:
                common.append((value, {}))
        else:
            unique.append(i)
            
    # Default split/compare assignment
    if len(unique) == 0:
        splits = []
        compares = []
    elif len(unique) == 1:
        splits = [unique[0]]
        compares = []
    else:
        splits = unique[:-1]
        compares = [unique[-1]]
        
    return common, splits, compares

def group_by_splits(messages: List[Message], splits: List[int], compares: List[int]) -> Dict:
    """Group messages by split dimensions"""
    groups = defaultdict(list)
    
    for msg in messages:
        components = parse_cascade_id(msg.cascade_id)
        
        # Build split key
        if splits:
            split_components = []
            for i in splits:
                name, params = components[i]
                param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items())) if params else ""
                split_components.append((name, param_str))
            split_key = tuple(split_components)
        else:
            split_key = ('all',)
            
        # Build compare key
        if compares:
            compare_components = []
            for i in compares:
                name, params = components[i]
                param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items())) if params else ""
                compare_components.append((name, param_str))
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
        
    # Analyze cascade paths
    common, default_splits, default_compares = analyze_cascade_paths(messages)
    
    # Get all possible split/compare positions
    components = parse_cascade_id(messages[0].cascade_id)
    all_positions = list(range(len(components)))
    
    # Create format function for positions
    def format_position(pos):
        name, params = components[pos]
        return format_step(name, params)
    
    # UI for selecting split/compare dimensions
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Split Dimensions")
        splits = st.multiselect(
            "Select split dimensions",
            all_positions,
            default=default_splits,
            format_func=format_position
        )
        
    with col2:
        st.subheader("Compare Dimensions")
        compares = st.multiselect(
            "Select compare dimensions",
            all_positions,
            default=default_compares,
            format_func=format_position
        )
    
    # Group messages
    groups = group_by_splits(messages, splits, compares)
    
    # Display groups
    for split_key, group in groups.items():
        # Format split key for display
        split_display = []
        for pos in splits:
            name, params = components[pos]
            split_display.append(format_step(name, params))
        st.header(f"Split: {' / '.join(split_display)}")
        
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
                for pos in compares:
                    name, params = components[pos]
                    compare_display.append(format_step(name, params))
                st.subheader(f"Compare: {' / '.join(compare_display)}")
                
                # Get steps from compare dimensions
                compare_steps = set()
                for pos in compares:
                    name, _ = components[pos]
                    compare_steps.add(name)
                
                # Display compare dimension values first
                for step, data in history.items():
                    if step in compare_steps:
                        st.write(f"**{step}:**")
                        if isinstance(data, dict) and 'image' in data:
                            # Handle image data
                            image_path = Path(project_name).parent / data['image']
                            if image_path.exists():
                                st.image(str(image_path))
                            else:
                                st.warning(f"Image not found: {image_path}")
                                
                            # Show other metadata
                            other_data = {k:v for k,v in data.items() if k != 'image'}
                            if other_data:
                                st.json(other_data)
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
                                # Handle image data
                                image_path = Path(project_name).parent / data['image']
                                if image_path.exists():
                                    st.image(str(image_path))
                                else:
                                    st.warning(f"Image not found: {image_path}")
                                    
                                # Show other metadata
                                other_data = {k:v for k,v in data.items() if k != 'image'}
                                if other_data:
                                    st.json(other_data)
                            elif isinstance(data, (dict, list)):
                                # Show JSON data
                                st.json(data)
                            else:
                                # Show string/primitive data
                                st.write(data)

if __name__ == "__main__":
    import asyncio
    main()
