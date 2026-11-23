"""Disposable Hermes model-provider plugin for the offline print trial."""
import os
from agent.acp_client import ACPClient
from providers import register_provider
from providers.base import ProviderProfile


class PrintClient(ACPClient):
    default_command = "docker.exe"
    default_args = ()
    command_env_vars = ("MESH_PRINT_TRIAL_COMMAND",)
    args_env_var = "MESH_PRINT_TRIAL_ARGS"
    marker_base_url = "acp://mesh-print-trial"
    placeholder_model = "tinyllama-1.1b-cpu" if os.environ.get("MESH_PRINT_TRIAL_MODEL") == "tinyllama" else "offline-calculator"
    label = "Offline print trial"

    def _session(self, timeout_seconds, *, allow_file_requests=False):
        return super()._session(timeout_seconds, allow_file_requests=False)

    def _create_chat_completion(self, *, tools=None, tool_choice=None, stream=False, **kwargs):
        if stream:
            raise ValueError("The print trial expects one complete answer")
        answer = super()._create_chat_completion(**kwargs)
        if answer.choices[0].message.tool_calls:
            raise ValueError("The print calculator must return its result directly")
        return answer


class PrintProfile(ProviderProfile):
    def create_client(self, **kwargs):
        return PrintClient(**kwargs)


register_provider(PrintProfile(name="mesh-print-trial", api_mode="chat_completions", env_vars=(),
                               base_url=PrintClient.marker_base_url, auth_type="external_process",
                               process_command=PrintClient.default_command,
                               process_command_env_vars=PrintClient.command_env_vars,
                               process_args_env_var=PrintClient.args_env_var,
                               static_models=(PrintClient.placeholder_model,)))
