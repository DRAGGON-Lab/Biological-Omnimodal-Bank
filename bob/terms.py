"""Ontology terms used in BOB's exports. Each was looked up in its ontology (OBI and BAO through
EBI's Ontology Lookup Service, EDAM in the archived 1.25 release) rather than written from memory."""

OBI = "http://purl.obolibrary.org/obo/OBI_"
BAO = "http://www.bioassayontology.org/bao#BAO_"
EDAM = "http://edamontology.org/"

XLSX_FORMAT = EDAM + "format_3620"
SBOL_FORMAT = EDAM + "format_3725"
ISA_JSON_FORMAT = EDAM + "format_4069"

# A plate-reader signal's kind, as the variable it measures.
SIGNAL_TERMS = {
    "absorbance": (BAO + "0000070", "absorbance"),
    "fluorescence": (BAO + "0000363", "fluorescence intensity"),
}

ONTOLOGY_SOURCES = [
    {"name": "OBI", "file": "http://purl.obolibrary.org/obo/obi.owl", "version": "", "description": "Ontology for Biomedical Investigations", "comments": []},
    {"name": "EDAM", "file": "http://edamontology.org/EDAM.owl", "version": "1.25", "description": "EDAM, an ontology of bioscientific data analysis and data management", "comments": []},
]
