# Copyright (c) Microsoft. All rights reserved.

from logging import Logger
from typing import List, Optional, Tuple, Union

import google.generativeai as palm
from google.generativeai.types import ChatResponse, ExampleOptions, MessagePromptOptions
from pydantic import PrivateAttr, constr

from semantic_kernel.connectors.ai.ai_exception import AIException
from semantic_kernel.connectors.ai.ai_service_client_base import AIServiceClientBase
from semantic_kernel.connectors.ai.chat_completion_client_base import (
    ChatCompletionClientBase,
)
from semantic_kernel.connectors.ai.chat_request_settings import ChatRequestSettings
from semantic_kernel.connectors.ai.complete_request_settings import (
    CompleteRequestSettings,
)
from semantic_kernel.connectors.ai.text_completion_client_base import (
    TextCompletionClientBase,
)


class GooglePalmChatCompletion(
    ChatCompletionClientBase, TextCompletionClientBase, AIServiceClientBase
):
    api_key: constr(strip_whitespace=True, min_length=1)
    _message_history: Optional[ChatResponse] = PrivateAttr()

    def __init__(
        self,
        ai_model_id: str,
        api_key: str,
        message_history: Optional[ChatResponse] = None,
        log: Optional[Logger] = None,
    ):
        """
        Initializes a new instance of the GooglePalmChatCompletion class.

        Arguments:
            ai_model_id {str} -- GooglePalm model name, see
                https://developers.generativeai.google/models/language
            api_key {str} -- GooglePalm API key, see
                https://developers.generativeai.google/products/palm
            message_history {Optional[ChatResponse]} -- The message history to use for context. (Optional)
            log {Optional[Logger]} -- The logger instance to use. (Optional)
        """
        super().__init__(
            ai_model_id=ai_model_id,
            api_key=api_key,
            log=log,
        )
        self._message_history = message_history

    async def complete_chat_async(
        self,
        messages: List[Tuple[str, str]],
        request_settings: ChatRequestSettings,
        context: Optional[str] = None,
        examples: Optional[ExampleOptions] = None,
        prompt: Optional[MessagePromptOptions] = None,
    ) -> Union[str, List[str]]:
        response = await self._send_chat_request(
            messages, request_settings, context, examples, prompt
        )

        if request_settings.number_of_responses > 1:
            return [
                candidate["output"]
                if candidate["output"] is not None
                else "I don't know."
                for candidate in response.candidates
            ]
        return "I don't know." if response.last is None else response.last

    async def complete_chat_stream_async(
        self,
        messages: List[Tuple[str, str]],
        request_settings: ChatRequestSettings,
        context: Optional[str] = None,
    ):
        raise NotImplementedError(
            "Google Palm API does not currently support streaming"
        )

    async def complete_async(
        self,
        prompt: str,
        request_settings: CompleteRequestSettings,
        logger: Optional[Logger] = None,
    ) -> Union[str, List[str]]:
        prompt_to_message = [("user", prompt)]
        chat_settings = ChatRequestSettings(
            temperature=request_settings.temperature,
            top_p=request_settings.top_p,
            presence_penalty=request_settings.presence_penalty,
            frequency_penalty=request_settings.frequency_penalty,
            max_tokens=request_settings.max_tokens,
            number_of_responses=request_settings.number_of_responses,
            token_selection_biases=request_settings.token_selection_biases,
        )
        response = await self._send_chat_request(prompt_to_message, chat_settings)

        if chat_settings.number_of_responses > 1:
            return [
                candidate["output"]
                if candidate["output"] is not None
                else "I don't know."
                for candidate in response.candidates
            ]
        return "I don't know." if response.last is None else response.last

    async def complete_stream_async(
        self,
        prompt: str,
        request_settings: CompleteRequestSettings,
        logger: Optional[Logger] = None,
    ):
        raise NotImplementedError(
            "Google Palm API does not currently support streaming"
        )

    async def _send_chat_request(
        self,
        messages: List[Tuple[str, str]],
        request_settings: ChatRequestSettings,
        context: Optional[str] = None,
        examples: Optional[ExampleOptions] = None,
        prompt: Optional[MessagePromptOptions] = None,
    ):
        """
        Completes the given user message. If len(messages) > 1, and a
        conversation has not been initiated yet, it is assumed that chat history
        is needed for context. All messages preceding the last message will be
        utilized for context. This also enables Google PaLM to utilize memory
        and skills, which should be stored in the messages parameter as system
        messages.

        Arguments:
            messages {str} -- The message (from a user) to respond to.
            request_settings {ChatRequestSettings} -- The request settings.
            context {str} -- Text that should be provided to the model first,
            to ground the response. If a system message is provided, it will be
            used as context.
            examples {ExamplesOptions} -- 	Examples of what the model should
            generate. This includes both the user input and the response that
            the model should emulate. These examples are treated identically to
            conversation messages except that they take precedence over the
            history in messages: If the total input size exceeds the model's
            input_token_limit the input will be truncated. Items will be dropped
            from messages before examples
            See: https://developers.generativeai.google/api/python/google/generativeai/types/ExampleOptions
            prompt {MessagePromptOptions} -- 	You may pass a
            types.MessagePromptOptions instead of a setting context/examples/messages,
            but not both.
            See: https://developers.generativeai.google/api/python/google/generativeai/types/MessagePromptOptions

        Returns:
            str -- The completed text.
        """
        if request_settings is None:
            raise ValueError("The request settings cannot be `None`")

        if request_settings.max_tokens < 1:
            raise AIException(
                AIException.ErrorCodes.InvalidRequest,
                "The max tokens must be greater than 0, "
                f"but was {request_settings.max_tokens}",
            )

        if len(messages) <= 0:
            raise AIException(
                AIException.ErrorCodes.InvalidRequest,
                "To complete a chat you need at least one message",
            )

        if messages[-1][0] != "user":
            raise AIException(
                AIException.ErrorCodes.InvalidRequest,
                "The last message must be from the user",
            )
        try:
            palm.configure(api_key=self.api_key)
        except Exception as ex:
            raise PermissionError(
                "Google PaLM service failed to configure. Invalid API key provided.",
                ex,
            )
        if (
            self._message_history is None and context is None
        ):  # If the conversation hasn't started yet and no context is provided
            context = ""
            if len(messages) > 1:  # Check if we need context from messages
                for index, (role, message) in enumerate(messages):
                    if index < len(messages) - 1:
                        context += message + "\n" if role == "system" else f"{role}: {message}" + "\n"
        try:
            if self._message_history is None:
                response = palm.chat(  # Start a new conversation
                    model=self.ai_model_id,
                    context=context,
                    examples=examples,
                    temperature=request_settings.temperature,
                    candidate_count=request_settings.number_of_responses,
                    top_p=request_settings.top_p,
                    prompt=prompt,
                    messages=messages[-1][1],
                )
            else:
                response = self._message_history.reply(  # Continue the conversation
                    messages[-1][1],
                )
            self._message_history = response  # Store response object for future use
        except Exception as ex:
            raise AIException(
                AIException.ErrorCodes.ServiceError,
                "Google PaLM service failed to complete the prompt",
                ex,
            )
        return response
