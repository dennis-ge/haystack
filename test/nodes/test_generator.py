import sys
from typing import List
from unittest.mock import patch, create_autospec

import pytest
from haystack import Pipeline
from haystack.schema import Document
from haystack.nodes.answer_generator import Seq2SeqGenerator, OpenAIAnswerGenerator, RAGenerator
from haystack.pipelines import GenerativeQAPipeline
from haystack.nodes import PromptTemplate

import logging
from ..conftest import fail_at_version


@pytest.mark.unit
@fail_at_version(1, 18)
def test_seq2seq_deprecation():
    with pytest.warns(DeprecationWarning):
        try:
            Seq2SeqGenerator("non_existing_model/model")
        except OSError:
            pass


@pytest.mark.unit
@fail_at_version(1, 18)
def test_rag_deprecation():
    with pytest.warns(DeprecationWarning):
        try:
            RAGenerator("non_existing_model/model")
        except OSError:
            pass


@pytest.mark.skipif(sys.platform in ["win32", "cygwin"], reason="Causes OOM on windows github runner")
@pytest.mark.integration
@pytest.mark.generator
def test_rag_token_generator(rag_generator, docs_with_true_emb):
    query = "What is capital of the Germany?"
    generated_docs = rag_generator.predict(query=query, documents=docs_with_true_emb, top_k=1)
    answers = generated_docs["answers"]
    assert len(answers) == 1
    assert "berlin" in answers[0].answer


@pytest.mark.skipif(sys.platform in ["win32", "cygwin"], reason="Causes OOM on windows github runner")
@pytest.mark.integration
@pytest.mark.generator
@pytest.mark.parametrize("document_store", ["memory"], indirect=True)
@pytest.mark.parametrize("retriever", ["embedding"], indirect=True)
def test_generator_pipeline(document_store, retriever, rag_generator, docs_with_true_emb):
    document_store.write_documents(docs_with_true_emb)
    query = "What is capital of the Germany?"
    pipeline = GenerativeQAPipeline(retriever=retriever, generator=rag_generator)
    output = pipeline.run(query=query, params={"Generator": {"top_k": 2}, "Retriever": {"top_k": 1}})
    answers = output["answers"]
    assert len(answers) == 2
    assert "berlin" in answers[0].answer
    for doc_idx, document in enumerate(output["documents"]):
        assert document.id == answers[0].document_ids[doc_idx]
        assert document.meta == answers[0].meta["doc_metas"][doc_idx]


@pytest.mark.skipif(sys.platform in ["win32", "cygwin"], reason="Causes OOM on windows github runner")
@pytest.mark.integration
@pytest.mark.generator
@pytest.mark.parametrize("document_store", ["memory"], indirect=True)
@pytest.mark.parametrize("retriever", ["retribert", "dpr_lfqa"], indirect=True)
@pytest.mark.parametrize("lfqa_generator", ["yjernite/bart_eli5", "vblagoje/bart_lfqa"], indirect=True)
@pytest.mark.embedding_dim(128)
def test_lfqa_pipeline(document_store, retriever, lfqa_generator, docs_with_true_emb):
    # reuse existing DOCS but regenerate embeddings with retribert
    docs: List[Document] = []
    for d in docs_with_true_emb:
        docs.append(Document(content=d.content))
    document_store.write_documents(docs)
    document_store.update_embeddings(retriever)
    query = "Tell me about Berlin?"
    pipeline = GenerativeQAPipeline(generator=lfqa_generator, retriever=retriever)
    output = pipeline.run(query=query, params={"top_k": 1})
    answers = output["answers"]
    assert len(answers) == 1, answers
    assert "Germany" in answers[0].answer, answers[0].answer


@pytest.mark.skipif(sys.platform in ["win32", "cygwin"], reason="Causes OOM on windows github runner")
@pytest.mark.integration
@pytest.mark.generator
@pytest.mark.parametrize("document_store", ["memory"], indirect=True)
@pytest.mark.parametrize("retriever", ["retribert"], indirect=True)
@pytest.mark.embedding_dim(128)
def test_lfqa_pipeline_unknown_converter(document_store, retriever, docs_with_true_emb):
    # reuse existing DOCS but regenerate embeddings with retribert
    docs: List[Document] = []
    for d in docs_with_true_emb:
        docs.append(Document(content=d.content))
    document_store.write_documents(docs)
    document_store.update_embeddings(retriever)
    seq2seq = Seq2SeqGenerator(model_name_or_path="patrickvonplaten/t5-tiny-random")
    query = "Tell me about Berlin?"
    pipeline = GenerativeQAPipeline(retriever=retriever, generator=seq2seq)

    # raises exception as we don't have converter for "patrickvonplaten/t5-tiny-random" in Seq2SeqGenerator
    with pytest.raises(Exception) as exception_info:
        output = pipeline.run(query=query, params={"top_k": 1})
    assert "doesn't have input converter registered for patrickvonplaten/t5-tiny-random" in str(exception_info.value)


@pytest.mark.integration
@pytest.mark.generator
@pytest.mark.parametrize("document_store", ["memory"], indirect=True)
@pytest.mark.parametrize("retriever", ["retribert"], indirect=True)
@pytest.mark.embedding_dim(128)
def test_lfqa_pipeline_invalid_converter(document_store, retriever, docs_with_true_emb):
    # reuse existing DOCS but regenerate embeddings with retribert
    docs: List[Document] = []
    for d in docs_with_true_emb:
        docs.append(Document(content=d.content))
    document_store.write_documents(docs)
    document_store.update_embeddings(retriever)

    class _InvalidConverter:
        def __call__(self, some_invalid_para: str, another_invalid_param: str) -> None:
            pass

    seq2seq = Seq2SeqGenerator(
        model_name_or_path="patrickvonplaten/t5-tiny-random", input_converter=_InvalidConverter()
    )
    query = "This query will fail due to InvalidConverter used"
    pipeline = GenerativeQAPipeline(retriever=retriever, generator=seq2seq)

    # raises exception as we are using invalid method signature in _InvalidConverter
    with pytest.raises(Exception) as exception_info:
        output = pipeline.run(query=query, params={"top_k": 1})
    assert "does not have a valid __call__ method signature" in str(exception_info.value)


@pytest.mark.integration
@pytest.mark.parametrize("haystack_openai_config", ["openai", "azure"], indirect=True)
def test_openai_answer_generator(haystack_openai_config, docs):
    if not haystack_openai_config:
        pytest.skip("No API key found, skipping test")

    openai_generator = OpenAIAnswerGenerator(
        api_key=haystack_openai_config["api_key"],
        azure_base_url=haystack_openai_config.get("azure_base_url", None),
        azure_deployment_name=haystack_openai_config.get("azure_deployment_name", None),
        model="text-babbage-001",
        top_k=1,
    )
    prediction = openai_generator.predict(query="Who lives in Berlin?", documents=docs, top_k=1)
    assert len(prediction["answers"]) == 1
    assert "Carla" in prediction["answers"][0].answer


@pytest.mark.integration
@pytest.mark.parametrize("haystack_openai_config", ["openai", "azure"], indirect=True)
def test_openai_answer_generator_custom_template(haystack_openai_config, docs):
    if not haystack_openai_config:
        pytest.skip("No API key found, skipping test")

    lfqa_prompt = PromptTemplate(
        """Synthesize a comprehensive answer from your knowledge and the following topk most relevant paragraphs and
        the given question.\n===\Paragraphs: {context}\n===\n{query}"""
    )
    node = OpenAIAnswerGenerator(
        api_key=haystack_openai_config["api_key"],
        azure_base_url=haystack_openai_config.get("azure_base_url", None),
        azure_deployment_name=haystack_openai_config.get("azure_deployment_name", None),
        model="text-babbage-001",
        top_k=1,
        prompt_template=lfqa_prompt,
    )
    prediction = node.predict(query="Who lives in Berlin?", documents=docs, top_k=1)
    assert len(prediction["answers"]) == 1


@pytest.mark.integration
@pytest.mark.parametrize("haystack_openai_config", ["openai", "azure"], indirect=True)
def test_openai_answer_generator_max_token(haystack_openai_config, docs, caplog):
    if not haystack_openai_config:
        pytest.skip("No API key found, skipping test")

    openai_generator = OpenAIAnswerGenerator(
        api_key=haystack_openai_config["api_key"],
        azure_base_url=haystack_openai_config.get("azure_base_url", None),
        azure_deployment_name=haystack_openai_config.get("azure_deployment_name", None),
        model="text-babbage-001",
        top_k=1,
    )
    openai_generator.MAX_TOKENS_LIMIT = 116
    with caplog.at_level(logging.INFO):
        prediction = openai_generator.predict(query="Who lives in Berlin?", documents=docs, top_k=1)
        assert "Skipping all of the provided Documents" in caplog.text
        assert len(prediction["answers"]) == 1
        # Can't easily check content of answer since it is generative and can change between runs


# mock tokenizer that splits the string
class MockTokenizer:
    def encode(self, *args, **kwargs):
        return str.split(*args, **kwargs)

    def tokenize(self, *args, **kwargs):
        return str.split(*args, **kwargs)


@pytest.mark.unit
def test_build_prompt_within_max_length():
    with patch("haystack.nodes.answer_generator.openai.load_openai_tokenizer") as mock_load_tokenizer:
        mock_load_tokenizer.return_value = MockTokenizer()

        generator = OpenAIAnswerGenerator(api_key="fake_key", max_tokens=50)
        generator.MAX_TOKENS_LIMIT = 92
        query = "query"
        documents = [Document("most relevant document"), Document("less relevant document")]
        prompt_str, prompt_docs = generator._build_prompt_within_max_length(query=query, documents=documents)

        assert len(prompt_docs) == 1
        assert prompt_docs[0] == documents[0]


@pytest.mark.unit
def test_openai_answer_generator_pipeline_max_tokens():
    """
    tests that the max_tokens parameter is passed to the generator component in the pipeline
    """
    question = "What is New York City like?"
    mocked_response = "Forget NYC, I was generated by the mock method."
    nyc_docs = [Document(content="New York is a cool and amazing city to live in the United States of America.")]
    pipeline = Pipeline()

    # mock load_openai_tokenizer to avoid accessing the internet to init tiktoken
    with patch("haystack.nodes.answer_generator.openai.load_openai_tokenizer"):
        openai_generator = OpenAIAnswerGenerator(api_key="fake_api_key", model="text-babbage-001", top_k=1)

        pipeline.add_node(component=openai_generator, name="generator", inputs=["Query"])
        openai_generator.run = create_autospec(openai_generator.run)
        openai_generator.run.return_value = ({"answers": mocked_response}, "output_1")

        result = pipeline.run(query=question, documents=nyc_docs, params={"generator": {"max_tokens": 3}})
        assert result["answers"] == mocked_response
        openai_generator.run.assert_called_with(query=question, documents=nyc_docs, max_tokens=3)
