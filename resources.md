# NASA PSI Resource Map

These are the primary sources for the ingestion and retrieval work. Keep source URLs attached to every catalog record so the dashboard can show provenance.

- NASA Physical Sciences Informatics: https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation
- NASA PSI database tutorial: https://assets.science.nasa.gov/content/dam/science/bps/bps-general/bps-data_osdr_psi/Complete_PSI_Database_Guide.pdf
- NASA PSI workspace tutorial: https://assets.science.nasa.gov/content/dam/science/bps/bps-general/bps-data_osdr_psi/PSI%20Tutorial_Portal%20%20Workspaces.pdf
- NASA Physical Sciences Informatics overview: https://science.nasa.gov/physical-sciences-informatics-psi
- NASA Space Apps challenge brief: the local `instruction` file

## AI training and evaluation path

Do not fine-tune a language model on raw PSI files as the first step. Build a versioned metadata corpus from investigation descriptions, publications, variables, units, and provenance. Use the optional host-run Ollama model only to rewrite grounded summaries, and evaluate it against scientist-authored questions with citation and numeric-faithfulness checks. Train a separate regression or ranking model only after enough structured experiment rows are available and the target variable is defined.
