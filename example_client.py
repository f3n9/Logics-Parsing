"""
Example client for Logics-Parsing API

Demonstrates how to use the RESTful API endpoints for document parsing.
"""

import requests
import base64
import json
from pathlib import Path


class LogicsParsingClient:
    """Client for interacting with Logics-Parsing API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the API server
        """
        self.base_url = base_url.rstrip('/')

    def health_check(self) -> dict:
        """
        Check API server health status.

        Returns:
            dict: Health status including model loading state
        """
        response = requests.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    def parse_file(
        self,
        image_path: str,
        prompt: str = "QwenVL HTML",
        system_prompt: str = "You are a helpful assistant",
        include_visualization: bool = True,
        strip_tags: bool = False,
        save_output: bool = True,
        output_dir: str = "outputs"
    ) -> dict:
        """
        Parse a document image file.

        Args:
            image_path: Path to the image file
            prompt: Model prompt
            system_prompt: System prompt
            include_visualization: Include bounding box visualization
            strip_tags: Apply tag stripping post-processing
            save_output: Save HTML and visualization to files
            output_dir: Directory to save outputs

        Returns:
            dict: API response with parsed HTML and optional visualization
        """
        # Prepare the file
        with open(image_path, 'rb') as f:
            files = {'file': (Path(image_path).name, f, 'image/png')}

            # Prepare form data
            data = {
                'prompt': prompt,
                'system_prompt': system_prompt,
                'include_visualization': include_visualization,
                'strip_tags': strip_tags
            }

            # Send request
            response = requests.post(
                f"{self.base_url}/parse",
                files=files,
                data=data
            )

        response.raise_for_status()
        result = response.json()

        # Save outputs if requested
        if save_output:
            self._save_outputs(result, image_path, output_dir)

        return result

    def parse_base64(
        self,
        image_path: str = None,
        image_base64: str = None,
        prompt: str = "QwenVL HTML",
        system_prompt: str = "You are a helpful assistant",
        include_visualization: bool = True,
        strip_tags: bool = False,
        save_output: bool = True,
        output_dir: str = "outputs"
    ) -> dict:
        """
        Parse a document using base64-encoded image.

        Args:
            image_path: Path to image file (will be base64 encoded)
            image_base64: Pre-encoded base64 image string
            prompt: Model prompt
            system_prompt: System prompt
            include_visualization: Include bounding box visualization
            strip_tags: Apply tag stripping post-processing
            save_output: Save HTML and visualization to files
            output_dir: Directory to save outputs

        Returns:
            dict: API response with parsed HTML and optional visualization
        """
        # Encode image if path provided
        if image_path and not image_base64:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')
        elif not image_base64:
            raise ValueError("Either image_path or image_base64 must be provided")

        # Prepare request
        payload = {
            'image_base64': image_base64,
            'prompt': prompt,
            'system_prompt': system_prompt,
            'include_visualization': include_visualization,
            'strip_tags': strip_tags
        }

        # Send request
        response = requests.post(
            f"{self.base_url}/parse_base64",
            json=payload
        )

        response.raise_for_status()
        result = response.json()

        # Save outputs if requested
        if save_output:
            self._save_outputs(result, image_path or "base64_image", output_dir)

        return result

    def _save_outputs(self, result: dict, image_path: str, output_dir: str):
        """Save HTML and visualization outputs to files."""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        request_id = result['request_id']
        base_name = Path(image_path).stem

        # Save HTML output
        html_path = output_path / f"{base_name}_{request_id}.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(result['html_output'])
        print(f"Saved HTML to: {html_path}")

        # Save visualization if available
        if result.get('visualization_base64'):
            viz_path = output_path / f"{base_name}_{request_id}_vis.png"
            viz_data = base64.b64decode(result['visualization_base64'])
            with open(viz_path, 'wb') as f:
                f.write(viz_data)
            print(f"Saved visualization to: {viz_path}")


def main():
    """Example usage of the client."""
    import argparse

    parser = argparse.ArgumentParser(description="Logics-Parsing API Client")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="API server URL"
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Path to image file to parse"
    )
    parser.add_argument(
        "--prompt",
        default="QwenVL HTML",
        help="Model prompt"
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory to save outputs"
    )
    parser.add_argument(
        "--use-base64",
        action="store_true",
        help="Use base64 endpoint instead of file upload"
    )
    parser.add_argument(
        "--no-viz",
        action="store_true",
        help="Skip visualization generation"
    )

    args = parser.parse_args()

    # Create client
    client = LogicsParsingClient(base_url=args.url)

    # Check health
    print("Checking API health...")
    health = client.health_check()
    print(f"API Status: {health['status']}")
    print(f"Model Loaded: {health['model_loaded']}")

    if not health['model_loaded']:
        print("ERROR: Model not loaded on server. Cannot proceed.")
        return

    # Parse document
    print(f"\nParsing document: {args.image}")
    try:
        if args.use_base64:
            result = client.parse_base64(
                image_path=args.image,
                prompt=args.prompt,
                include_visualization=not args.no_viz,
                output_dir=args.output_dir
            )
        else:
            result = client.parse_file(
                image_path=args.image,
                prompt=args.prompt,
                include_visualization=not args.no_viz,
                output_dir=args.output_dir
            )

        print(f"\nRequest ID: {result['request_id']}")
        print(f"Input dimensions: {result['input_dimensions']['width']}x{result['input_dimensions']['height']}")
        print(f"\nHTML output preview (first 500 chars):")
        print(result['html_output'][:500])
        print("...")

    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()
