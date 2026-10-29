---
name: research-and-record-city-population-data
description: "Find the 2024 population estimate for a specific city online and record it in a research spreadsheet. Learned from a recorded demonstration (Chrome, Sheets). 1 step(s) must be confirmed by a human before running."
---

# Research and Record City Population Data

**Goal:** Find the 2024 population estimate for a specific city online and record it in a research spreadsheet.

Learned from a 20-second screen recording. Follow the steps in order; after each one, check the expected result before moving on. Where a step says **Ask a human first**, stop and get confirmation: the recording alone was not enough to be sure.

## Inputs

Ask for these if they were not given, and use them wherever `{{name}}` appears.

- `{{search_query}}`: The query used to find population data. (example: city population 2024)
- `{{city_name}}`: The name of the city being researched. (example: Springfield)
- `{{spreadsheet_file}}`: The name of the spreadsheet file where data is recorded. (example: City Research.xlsx)
- `{{target_cell}}`: The specific cell where the population value should be entered. (example: B2)

## Before you start

- Access to a web browser with internet connectivity
- Access to the '{{spreadsheet_file}}' spreadsheet

## Steps

1. **Search for city population data**: In Chrome, type '{{search_query}}' into the Searchly search bar and click the 'Search' button.
   - Do: `type` `{{search_query}}` into `Search` (Chrome - Searchly)
   - Check: Search results for the query are displayed.
2. **Navigate to official city data**: Click on the first search result link titled '{{city_name}} - Official City Data'.
   - Do: `click` on `{{city_name}} - Official City Data` (Chrome - Searchly)
   - Check: The browser navigates to the official city data page for {{city_name}}.
3. **Identify the 2024 population estimate**: Locate and read the population estimate for 2024 on the city data page.
   - Do: `read` and note the value (it was `168,412` in the recording) from `Population (2024 estimate):` (Chrome - https://springfield.example/data)
   - Check: The population value '168,412' is identified.
4. **Record population in spreadsheet**: Switch to the '{{spreadsheet_file}}' spreadsheet and type the population value into cell {{target_cell}} for {{city_name}}, then wait for the 'All changes saved' confirmation.
   - Do: `type` the value read in step 3 (recorded: `186,412`) on `Cell {{target_cell}}` (Sheets - City Research.xlsx)
   - Check: The value is entered and the spreadsheet confirms the changes are saved.
   - **Ask a human first.** Check: The value entered '186,412' differs from the value read '168,412' in the previous step, suggesting a transcription error.

## Open questions

Unresolved when the recording was analyzed; ask before relying on the answer.

- Should the population value '186,412' be corrected to '168,412' in the spreadsheet to match the source data?
