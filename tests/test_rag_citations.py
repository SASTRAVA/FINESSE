from engine.rag.citations import citation_record, verify_and_attach_citations


def test_citation_records_have_provenance_and_unknown_references_are_removed():
    record = citation_record("C1", {
        "doc_id": "doc-1", "version": 3, "title": "Invoice",
        "source_type": "UPLOAD", "lane": "finance", "sensitivity": "internal",
        "page_or_section": "Sheet 2", "char_start": 10, "char_end": 20,
        "vault_path": "vault/Invoice.md",
    }, "Invoice amount $125")
    result = verify_and_attach_citations("Amount is $125 [C1]. Missing [C99].", [record.as_dict()])
    assert result["answer_markdown"] == "Amount is $125 [C1]. Missing ."
    assert result["citations"] == [record.as_dict()]
    assert result["unverified_citation_warnings"]
