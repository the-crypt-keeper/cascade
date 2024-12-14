import asyncio
from pathlib import Path
from cascade_main import Cascade

async def main():
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Cascade Pipeline Runner')
    parser.add_argument('config', type=Path, help='Path to pipeline configuration')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()
    
    # Run pipeline
    cascade = Cascade(args.config, debug=args.debug)
    await cascade.setup()
    await cascade.run()

if __name__ == '__main__':
    asyncio.run(main())
