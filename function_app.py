"""Iterate on generated content with a human-in-the-loop Durable orchestration.

Components used in this sample:
- AzureOpenAIChatClient for a single writer agent that emits structured JSON.
- AgentFunctionApp with Durable orchestration, HTTP triggers, and activity triggers.
- External events that pause the workflow until a human decision arrives or times out.

Prerequisites: configure `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`, and
either `AZURE_OPENAI_API_KEY` or sign in with Azure CLI before running `func start`."""

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from random import random
from typing import Any, cast

import azure.functions as func
from agent_framework.azure import AgentFunctionApp, AzureOpenAIChatClient
from azure.durable_functions import DurableOrchestrationClient, DurableOrchestrationContext
from azure.identity import AzureCliCredential
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# 1. Define orchestration constants used throughout the workflow.
FLIGHT_INFO_AGENT_NAME = "FlightInfoAgent"
USER_CHOICE_PROCESSOR_AGENT_NAME = "UserChoiceProcessorAgent"
TRAVEL_SUMMARY_AGENT_NAME = "TravelSummaryAgent"
USER_CHOICE_EVENT = "UserChoiceEvent"


class FlightOption(BaseModel):
    flight_number: str
    price: float
    departure_datetime: str
    arrival_datetime: str
    departure_city: str
    destination_city: str


class UserChoice(BaseModel):
    selection: int | None = None
    refinement_prompt: str | None = None


def _generate_flight_info(
        origin_city: str,
        destination_city: str,
        departure_datetime: str,
        max_departure_window_hours: int,
        max_price: float,
    ) -> list[FlightOption]:
    """Generate a list of flight options based on search criteria."""
    
    try:
        base_dt = datetime.fromisoformat(departure_datetime)
    except ValueError:
        base_dt = datetime.utcnow()

    count = random.randint(2, 10)

    flights: list[FlightOption] = []
    for i in range(count):
        # Airline code: simple random 3-letter code
        airline = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
        flight_number = f"{airline}{random.randint(0, 9999):04d}"

        dep_offset_hours = random.uniform(max_departure_window_hours * -1, max_departure_window_hours)
        dep_dt = base_dt + timedelta(hours=dep_offset_hours)
        flight_duration_hours = random.uniform(1, 6)
        arr_dt = dep_dt + timedelta(hours=flight_duration_hours)
        price = random.uniform(100, max_price)

        flights.append(
            FlightOption(
                flight_number=flight_number,
                price=round(price, 2),
                departure_datetime=dep_dt.isoformat(),
                arrival_datetime=arr_dt.isoformat(),
                departure_city=origin_city,
                destination_city=destination_city,
            )
        )

    return flights


# 2. Create the writer agent that produces structured JSON responses.
def _create_agents() -> Any:

    client = AzureOpenAIChatClient(credential=AzureCliCredential())

    flight_info_agent_instructions = """
        You provide a list of flight options based on user search criteria.
        Use the configured tools to generate the list and return as JSON with the following structure:

            {
                "flights": [
                    {
                        "flight_number": "string",
                        "price": float,
                        "departure_datetime": "ISO 8601 datetime string",
                        "arrival_datetime": "ISO 8601 datetime string",
                        "departure_city": "string",
                        "destination_city": "string"
                    },
                    ...
                ]
            }

        Ensure that the flight options respect the user's criteria, including departure city,
        destination city, departure datetime, and any specified maximum departure window and/or maximum price.
        If max departure window or max price are not specified, use reasonable defaults (e.g., 6 hours for departure window, $1000 for max price).
    """

    flight_info_agent = client.create_agent(
        name=FLIGHT_INFO_AGENT_NAME,
        instructions=flight_info_agent_instructions,
        tools=[_generate_flight_info],
        
    )

    user_choice_agent_instructions = """
        You help interpret a user's natural language feedback about a list of flight options.
        Given the user's feedback, decide whether they are selecting one of the flights by index,
        or refining/changing the search criteria.
        Always respond as JSON with the following structure:

            {
                "selection": int | null,
                "refinement_prompt": "string" | null
            }
        
        If the user is selecting a flight, set 'selection' to the 1-based index of the flight and set 'refinement_prompt' to null.
        If the user is refining the search, set 'refinement_prompt' to the clarifying instructions and set 'selection' to null.
        There should always be exactly one of 'selection' or 'refinement_prompt' set to a non-null value, and one set to null.
    """
    
    user_choice_agent = client.create_agent(
        name=USER_CHOICE_PROCESSOR_AGENT_NAME,
        instructions=user_choice_agent_instructions,
    )

    summary_agent_instructions = """
        You summarize the details of a customer interaction in which they have reviewed, refined, and chosen a flight itinerary.
        Use the details of the full conversation thread to summarize the user's interactions and the final selected flight.
        Provide a concise summary suitable for logging or notification purposes.
        NEVER ask the user what to do next; simply summarize the interaction and the final choice.
    """

    summary_agent = client.create_agent(
        name=TRAVEL_SUMMARY_AGENT_NAME,
        instructions=summary_agent_instructions,
    )

    return [flight_info_agent, user_choice_agent, summary_agent]


app = AgentFunctionApp(agents=_create_agents(), enable_health_check=True)


# 3. Activities encapsulate external work for review notifications and publishing.
@app.activity_trigger(input_name="content")
def notify_user(content: dict) -> None:
    flights = [FlightOption.model_validate(item) for item in content.get("flights", [])]
    logger.info("NOTIFICATION: Please review the following flight options:")
    if not flights:
        logger.info("No flights available.")
    for idx, flight in enumerate(flights, start=1):
        logger.info(
            "[%d] %s | %s -> %s | Departs: %s | Arrives: %s | Price: $%.2f",
            idx,
            flight.flight_number,
            flight.departure_city,
            flight.destination_city,
            flight.departure_datetime,
            flight.arrival_datetime,
            flight.price,
        )
    logger.info(
        "Use the approval endpoint to choose a flight by index or provide a clarifying prompt."
    )


@app.activity_trigger(input_name="content")
def summarize(content: str) -> None:
    logger.info(content)


# 4. Orchestration loops until the human approves, times out, or attempts are exhausted.
@app.orchestration_trigger(context_name="context")
def travel_orchestration(context: DurableOrchestrationContext):

    prompt = context.get_input()

    context.set_custom_status("Starting flight search")

    flight_info_agent = app.get_agent(context, FLIGHT_INFO_AGENT_NAME)
    choice_processor_agent = app.get_agent(context, USER_CHOICE_PROCESSOR_AGENT_NAME)
    summary_agent = app.get_agent(context, TRAVEL_SUMMARY_AGENT_NAME)

    agent_thread = flight_info_agent.get_new_thread()

    attempt = 0
    max_attempts = 3

    while attempt < max_attempts:
        attempt += 1

        context.set_custom_status(f"Generating flight options. Iteration #{attempt}.")

        flight_info_agent_result = yield flight_info_agent.run(
            messages=prompt,
            thread=agent_thread
        )

        flights_json = json.loads(flight_info_agent_result["response"])

        context.set_custom_status(f"Requesting choice of flight or further refinement. Iteration #{attempt}. 1 hour max wait time.")

        yield context.call_activity("notify_user", flights_json)

        choice_task = context.wait_for_external_event(USER_CHOICE_EVENT)

        timeout_task = context.create_timer(
            context.current_utc_datetime + timedelta(hours=1)
        )

        winner = yield context.task_any([choice_task, timeout_task])

        if winner == choice_task:

            timeout_task.cancel()  # type: ignore[attr-defined]

            choice_processor_agent_result = yield choice_processor_agent.run(
                messages=choice_task.result,
                thread=agent_thread,
                response_format=UserChoice
            )

            choice = cast(UserChoice, _coerce_structured(choice_processor_agent_result, UserChoice))

            if choice.selection is not None:
                index = choice.selection - 1

                flights = flights_json.get("flights", [])

                if index < 0 or index >= len(flights):
                    raise ValueError("Selected flight index is out of range.")

                selected_flight = FlightOption.model_validate(flights[index])

                context.set_custom_status("Flight selected by human reviewer. Summarizing flight...")

                summary_result = yield summary_agent.run(
                    messages=selected_flight.model_dump(),
                    thread=agent_thread
                )

                yield context.call_activity("summarize", summary_result["response"])

                context.set_custom_status(
                    f"Flight booked successfully at {context.current_utc_datetime:%Y-%m-%dT%H:%M:%S}"
                )

                return {"flight": selected_flight.model_dump()}
            
            else:
                if choice.refinement_prompt is None or not choice.refinement_prompt.strip():
                    raise ValueError("Refinement prompt cannot be empty.")

                prompt = f"User refinement: {choice.refinement_prompt.strip()}"

                context.set_custom_status(f"Refinement received. Regenerating flight options. Iteration #{attempt}.")
            
        else:
            context.set_custom_status("User choice timed out. Treating as rejection.")
            raise TimeoutError("User choice timed out.")

    raise RuntimeError(f"Flight could not be selected after {max_attempts} iteration(s).")


# 5. HTTP endpoint that starts the human-in-the-loop orchestration.
@app.route(route="travel/run", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_orchestration(
    req: func.HttpRequest,
    client: DurableOrchestrationClient,
) -> func.HttpResponse:

    try:
        body = req.get_body().decode("utf-8")
    except ValueError:
        body = None

    instance_id = await client.start_new(
        orchestration_function_name="travel_orchestration",
        client_input=body,
    )

    status_url = _build_status_url(req.url, instance_id, route="travel")

    payload_json = {
        "message": "Flight search orchestration started.",
        "instanceId": instance_id,
        "statusQueryGetUri": status_url,
    }

    return func.HttpResponse(
        body=json.dumps(payload_json),
        status_code=202,
        mimetype="application/json",
    )


# 6. Endpoint that delivers human approval or rejection back into the orchestration.
@app.route(route="travel/choice/{instanceId}", methods=["POST"])
@app.durable_client_input(client_name="client")
async def send_human_approval(
    req: func.HttpRequest,
    client: DurableOrchestrationClient,
) -> func.HttpResponse:

    instance_id = req.route_params.get("instanceId")
    if not instance_id:
        return func.HttpResponse(
            body=json.dumps({"error": "Missing instanceId in route."}),
            status_code=400,
            mimetype="application/json",
        )

    await client.raise_event(instance_id, USER_CHOICE_EVENT, req.get_body().decode("utf-8"))

    return func.HttpResponse(status_code=200)


# 7. Endpoint that mirrors Durable Functions status plus custom workflow messaging.
@app.route(route="travel/status/{instanceId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_orchestration_status(
    req: func.HttpRequest,
    client: DurableOrchestrationClient,
) -> func.HttpResponse:
    instance_id = req.route_params.get("instanceId")
    if not instance_id:
        return func.HttpResponse(
            body=json.dumps({"error": "Missing instanceId"}),
            status_code=400,
            mimetype="application/json",
        )

    status = await client.get_status(
        instance_id,
        show_history=False,
        show_history_output=False,
        show_input=True,
    )
    
    # Check if status is None or if the instance doesn't exist (runtime_status is None)
    if status is None or getattr(status, "runtime_status", None) is None:
        return func.HttpResponse(
            body=json.dumps({"error": "Instance not found."}),
            status_code=404,
            mimetype="application/json",
        )

    response_data: dict[str, Any] = {
        "instanceId": getattr(status, "instance_id", None),
        "runtimeStatus": getattr(status.runtime_status, "name", None)
        if getattr(status, "runtime_status", None)
        else None,
        "workflowStatus": getattr(status, "custom_status", None),
    }

    if getattr(status, "input_", None) is not None:
        response_data["input"] = status.input_

    if getattr(status, "output", None) is not None:
        response_data["output"] = status.output

    failure_details = getattr(status, "failure_details", None)
    if failure_details is not None:
        response_data["failureDetails"] = failure_details

    return func.HttpResponse(
        body=json.dumps(response_data),
        status_code=200,
        mimetype="application/json",
    )


# 8. Helper utilities keep parsing logic deterministic.
def _build_status_url(request_url: str, instance_id: str, *, route: str) -> str:
    base_url, _, _ = request_url.partition("/api/")
    if not base_url:
        base_url = request_url.rstrip("/")
    return f"{base_url}/api/{route}/status/{instance_id}"


def _coerce_structured(result: Mapping[str, Any], model: type[BaseModel]) -> BaseModel:
    structured = result.get("structured_response") if isinstance(result, Mapping) else None
    if structured is not None:
        return model.model_validate(structured)

    response_text = result.get("response") if isinstance(result, Mapping) else None
    if isinstance(response_text, str) and response_text.strip():
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, Mapping):
                return model.model_validate(parsed)
        except json.JSONDecodeError:
            logger.warning("[ConditionalOrchestration] Failed to parse agent JSON response; raising error.")

    # If parsing failed, raise to surface the issue to the caller.
    raise ValueError(f"Agent response could not be parsed as {model.__name__}.")
