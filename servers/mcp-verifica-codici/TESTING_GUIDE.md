# Testing Guide: validate_folders Tool

## Overview
The `validate_folders` tool in mcp-verifica-codici v1.5.0 validates document codes by comparing extracted codes from PDF files against a master list.

## Setup in Intelligencebox

### 1. Ensure Plugin is Available
The plugin should automatically appear in intelligencebox after:
- ✅ Docker image pushed: `ghcr.io/intelligencebox-repo/mcp-verifica-codici:latest`
- ✅ Manifest updated to v1.5.0
- ✅ Changes committed and pushed to GitHub
- ⏳ Vercel auto-deployment completes (registry API)

### 2. Upload Test Files
You need to upload:
1. **Individual PDF documents** to validate (containing "CODICE IDENTIFICATIVO" tables)
2. **Master list PDF** ("Elenco Documenti") with expected codes

Example file structure in intelligencebox:
```
/dataai/my-collection/
  ├── 02-PE-DS-IE-R-RC-00.pdf     (document to validate)
  ├── 02-PE-DG-AB-C-DE-01.pdf     (document to validate)
  ├── ...
  └── elenco-documenti.pdf         (master list)
```

## Using the Tool

### Tool: `validate_folders`

**Parameters:**
- `documents_folder` (string): Path to folder containing PDFs to validate
  - Example: `/dataai/my-collection`
- `master_list_pdf` (string): Path to the master list PDF
  - Example: `/dataai/my-collection/elenco-documenti.pdf`

### Example Usage in Chat

```
Use validate_folders to check the documents in /dataai/technical-docs
against the master list at /dataai/technical-docs/elenco-documenti.pdf
```

### Expected Output

The tool returns a JSON response with:

```json
{
  "summary": {
    "total_pdfs_scanned": 45,
    "codes_extracted_successfully": 43,
    "extraction_failures": 2,
    "expected_codes_count": 44,
    "matching_count": 41,
    "missing_count": 3,
    "unexpected_count": 2
  },
  "matching": {
    "description": "Codici trovati nei documenti che corrispondono alla master list",
    "codes": ["ADRPMV02-PEDSIIE-RRC00-1", ...],
    "count": 41
  },
  "missing_from_documents": {
    "description": "Codici presenti nella master list ma non trovati nei documenti",
    "codes": ["ADRPMV03-PEDGGEN-EED01-0", ...],
    "count": 3
  },
  "unexpected_in_documents": {
    "description": "Codici trovati nei documenti ma non presenti nella master list",
    "codes": ["ADRPMV99-PETEST-ABC00-1", ...],
    "count": 2
  },
  "extraction_failures": {
    "description": "File per i quali l'estrazione del codice è fallita",
    "files": ["corrupted-file.pdf", "blank-page.pdf"],
    "count": 2
  },
  "details": {
    "description": "Dettaglio di tutti i file scansionati",
    "files": {
      "02-PE-DS-IE-R-RC-00.pdf": "ADRPMV02-PEDSIIE-RRC00-1",
      "corrupted-file.pdf": "ESTRAZIONE_FALLITA",
      ...
    }
  }
}
```

## Troubleshooting

### Plugin Not Visible
1. Check box-server logs for plugin loading errors
2. Verify registry API is deployed: `curl https://intelligencebox-plugins.vercel.app/api/registry`
3. Check if `verifica-codici` appears in the list

### OCR Extraction Failures
- Ensure PDF first page contains the "CODICE IDENTIFICATIVO" table
- Check if code format matches pattern: `ADRPMV##-PE####-[A-Z]##-#`
- PDFs must be searchable or have clear images (300 DPI recommended)

### Volume Mount Issues
- Ensure paths start with `/dataai/` (mapped to intelligencebox data directory)
- Verify files exist and are accessible from Docker container
- Check `needsFileAccess: true` is set in manifest (already configured)

## Code Format Requirements

### Individual Document Code (extracted from PDF)
Format in table: `ADRPMV 02 -- PE DS II E -- R RC 00 - 1`
Normalized: `ADRPMV02-PEDSIIE-RRC00-1`

### Master List Code (parsed from table)
Format in table: `ADRPMV 02 PE DS II E - - R RC 00 1`
Reconstructed: `ADRPMV02-PEDSIIE-RRC00-1`

Both formats are automatically normalized for comparison.

## Test Files Used

Reference test files (from development):
- Individual document: `/Users/pineapp/Downloads/02-PE-DS-IE-R-RC-00 (2).pdf`
- Master list: `/Users/pineapp/Downloads/_02-PE-DG-GEN-E-ED-00 (2).pdf`

These demonstrate the expected format and structure.
