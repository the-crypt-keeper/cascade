import streamlit as st
import sys
from pathlib import Path
import json
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from cascade_base import Cascade, Message

def parse_cascade_id(cascade_id: str) -> List[str]:
    """Split cascade ID into components, handling merge nodes"""
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
                    components.append(current)
                    current = ""
            else:
                current += cascade_id[i]
            i += 1
            
    if current:
        components.append(current)
        
    return components

def analyze_cascade_paths(messages: List[Message]) -> Tuple[List[str], List[str], List[str]]:
    """Analyze cascade paths to identify common and unique components"""
    # Get all unique values for each position
    position_values: Dict[int, Set[str]] = defaultdict(set)
    
    # Parse all cascade IDs
    parsed_paths = [parse_cascade_id(msg.cascade_id) for msg in messages]
    
    # Find unique values at each position
    for path in parsed_paths:
        for i, component in enumerate(path):
            position_values[i].add(component)
            
    # Categorize positions
    common = []  # Same value in all paths
    unique = []  # Different values across paths
    
    max_len = max(len(path) for path in parsed_paths)
    
    for i in range(max_len):
        if len(position_values[i]) == 1:
            common.append(list(position_values[i])[0])
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
        split_key = tuple(components[i] for i in splits) if splits else ('all',)
        
        # Build compare key
        compare_key = tuple(components[i] for i in compares) if compares else ('value',)
        
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
    all_positions = list(range(len(parse_cascade_id(messages[0].cascade_id))))
    
    # UI for selecting split/compare dimensions
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Split Dimensions")
        splits = st.multiselect(
            "Select split dimensions",
            all_positions,
            default=default_splits,
            format_func=lambda x: f"Position {x}"
        )
        
    with col2:
        st.subheader("Compare Dimensions")
        compares = st.multiselect(
            "Select compare dimensions",
            all_positions,
            default=default_compares,
            format_func=lambda x: f"Position {x}"
        )
    
    # Group messages
    groups = group_by_splits(messages, splits, compares)
    
    # Display groups
    for split_key, group in groups.items():
        st.header(f"Split: {' / '.join(str(x) for x in split_key)}")
        
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
                st.subheader(f"Compare: {' / '.join(str(x) for x in compare_key)}")
                
                # Display history
                for step, data in history.items():
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
                    else:
                        # Show regular data
                        st.json(data)

if __name__ == "__main__":
    import asyncio
    main()
