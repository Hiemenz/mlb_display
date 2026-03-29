"""
Thin wrapper over display_eink.py with a CLI.

Standalone CLI:
    python src/display.py --image output/scoreboard.bmp [--full-refresh] [--config PATH]
"""
import os
import sys
import argparse

# Allow running as a standalone script from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image
from display_eink import display_image, display_partial_regions
from refresh_tracker import needs_full_refresh
from config_loader import load_config, add_config_arg


def send_to_display(image_path, changed_regions=None, force_full=False):
    """
    Load image from path and push to e-ink.

    Args:
        image_path: Path to the image file to display
        changed_regions: List of (x, y, w, h) tuples for partial refresh, or None
        force_full: Force a full refresh even if partial is possible

    Returns:
        'full' or 'partial'
    """
    image = Image.open(image_path)
    if force_full or needs_full_refresh() or not changed_regions:
        display_image(image, output_filename=image_path)
        return 'full'
    else:
        display_partial_regions(image, changed_regions, output_filename=image_path)
        return 'partial'


def main():
    parser = argparse.ArgumentParser(
        description='Send an image file to the e-ink display',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python src/display.py --image resulting_image.bmp
  python src/display.py --image resulting_image.bmp --full-refresh
        ''',
    )
    parser.add_argument('--image', type=str, required=True,
                        help='Path to image file to display')
    parser.add_argument('--full-refresh', action='store_true',
                        help='Force a full e-ink refresh')
    add_config_arg(parser)
    args = parser.parse_args()

    if not os.path.isfile(args.image):
        print(f"Error: image file not found: {args.image}")
        sys.exit(1)

    mode = send_to_display(args.image, force_full=args.full_refresh)
    print(f"Display updated ({mode} refresh)")


if __name__ == '__main__':
    main()
