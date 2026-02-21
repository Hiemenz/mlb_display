
# MLB Game Tracker for E-Paper Display

## Overview
This project is designed to fetch, process, and display MLB game data on an e-paper display, specifically using the 7.5-inch model from Waveshare. The project utilizes data from the MLB API to display live game updates, standings, and weather conditions directly on the e-paper device.

## Features
- **Data Fetching**: Retrieves live game data, standings, and detailed team information from the MLB API.
- **Display on E-Paper**: Utilizes the Waveshare e-paper library to handle the physical display of data.
- **Weather Information**: Shows current weather conditions for games.
- **Game Statistics**: Displays live scores, innings, hits, errors, and team probabilities.

## Prerequisites
- Python 3.8 or higher.
- Access to MLB API for fetching game and team data.
- Waveshare e-paper display hardware and required libraries.
- Pillow library for image manipulation in Python.

## Installation and Setup
1. **Clone the Repository**: Clone the project to your local environment.
2. **Install Dependencies**:
   ```bash
   pip install requests Pillow
   ```
3. **Configure the Display**:
   Connect your e-paper display to your Raspberry Pi or similar device and verify the hardware connections.

## Usage
To run the project, navigate to the project directory and execute the main script:
```bash
python3 main.py
```
This will initiate the data fetching process and update the e-paper display accordingly.

## Scripts Description
- **`main.py`**: Coordinates the fetching of data and updating of the display.
- **`display_image.py`**: Handles the image rendering on the e-paper display.
- **`data_fetch.py`**: Contains functions to retrieve data from the MLB API and process it.
- **`image_generation.py`**: Functions to generate and manipulate images to be displayed based on the fetched data.

## Data Handling
- **JSON Files**: Stores configuration and temporary data in JSON files to manage state between updates.
- **Data Refresh**: The system automatically checks for new game data based on a configurable interval to keep the display updated.

## Customization
Users can customize the display information by modifying the configuration JSON files to select which game details or standings to show.

## Troubleshooting
- **Display Issues**: Ensure that the e-paper display is correctly connected and the Waveshare library is properly installed.
- **Data Fetching**: Check the MLB API access and ensure your network connection is stable.

## Contributing
Contributions to this project are welcome. Please fork the repository, make your changes, and submit a pull request.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.
