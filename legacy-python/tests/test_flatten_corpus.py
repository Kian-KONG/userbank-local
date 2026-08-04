from ub_local.pipeline.flatten_corpus import flatten_corpus


def test_flatten_corpus_basic():
    corpus = {
        "nodes": [
            {
                "id": "n1",
                "title": "Intro",
                "paragraphs": ["Hello world", {"type": "text", "content": "Second"}],
            }
        ]
    }
    chunks = flatten_corpus(corpus, "doc1")
    assert len(chunks) == 2
    assert chunks[0]["id"] == "doc1:n1:0"
    assert chunks[0]["text"] == "Hello world"
    assert chunks[1]["text"] == "Second"
