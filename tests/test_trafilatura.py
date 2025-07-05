import argparse
from ast import arg
import trafilatura
import requests

def test_parser_manager(downloaded, output_format='xml', include_formatting=True, include_links=True, include_tables=True, ansi_color=None):
    content = trafilatura.extract(downloaded, output_format=output_format, include_formatting=include_formatting, include_links=include_links, include_tables=include_tables, ansi_color=ansi_color is not None)
    
    if content is None:
        print("Failed to extract content.")
        return
    
    if output_format == 'xml':
        if ansi_color:
            print(f"\033[31m{content}\033[0m")
        else:
            print(content)
            
    if output_format == 'markdown':
        if ansi_color:
            print(f"\033[32m{content}\033[0m")
        else:
            print(content)

# Example usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Parse HTML content')
    parser.add_argument('source', type=str, help='URL of the page or path to HTML file')
    parser.add_argument('-x', '--xml', action='store_true', help='Output XML content')
    parser.add_argument('-m', '--markdown', action='store_true', help='Output Markdown content')
    parser.add_argument('-a', '--ansi', action='store_true', help='Output with ANSI colors')
    args = parser.parse_args()
    
    if args.source.startswith('http'):
        response = requests.get(args.source)
        downloaded = response.content
    else:
        with open(args.source, 'r') as file:
            downloaded = file.read()
    
    if args.xml:
        test_parser_manager(downloaded, output_format='xml', ansi_color=args.ansi)
        
    if args.markdown and args.xml:
        print("\n\n----------------------\n\n")
        
    if args.markdown:
        test_parser_manager(downloaded, output_format='markdown', ansi_color=args.ansi)
