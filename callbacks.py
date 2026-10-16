"""Trazas legibles de modelo y herramientas para la demostración."""
import os
from typing import Any
from langchain_core.callbacks import BaseCallbackHandler


class AgentCallbackHandler(BaseCallbackHandler):
    def __init__(self, verbose=None):
        self.verbose = os.getenv("STEWARD_VERBOSE", "0") == "1" if verbose is None else verbose

    def on_chat_model_start(self, serialized, messages, **kwargs: Any):
        print("\n[MODELO] Iniciando llamada...")
        if self.verbose:
            for batch in messages:
                for message in batch:
                    print(message.content)

    def on_llm_start(self, serialized, prompts, **kwargs: Any):
        print("\n[MODELO] Iniciando llamada...")
        if self.verbose:
            print("\n".join(prompts))

    def on_llm_end(self, response, **kwargs: Any):
        print("[RESPUESTA DEL MODELO]")
        for batch in response.generations:
            for generation in batch:
                print(generation.text)

    def on_llm_error(self, error, **kwargs: Any):
        print(f"[ERROR MODELO] {type(error).__name__}: {error}")

    def on_tool_start(self, serialized, input_str, **kwargs: Any):
        print(f"\n[TOOL START] {serialized.get('name', 'herramienta')} | entrada={input_str}")

    def on_tool_end(self, output, **kwargs: Any):
        print(f"[TOOL END] {output}")

    def on_tool_error(self, error, **kwargs: Any):
        print(f"[TOOL ERROR] {type(error).__name__}: {error}")
