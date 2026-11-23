import asyncio
import json
import logging

from engine.llm.concurrency_guard import PrioritySemaphore
from engine.observability.logging import RedactingJSONFormatter
from engine.observability.metrics import Metrics


def test_json_logging_redacts_sensitive_fields_and_payloads():
    record = logging.LogRecord("test", logging.INFO, __file__, 1,
                               "Bearer secretvaluehere admin@example.test password=p4ssword",
                               (), None)
    record.api_key = "secret"
    output = json.loads(RedactingJSONFormatter().format(record))
    assert "secretvaluehere" not in json.dumps(output)
    assert "admin@example.test" not in json.dumps(output)
    assert "p4ssword" not in json.dumps(output)


def test_metrics_have_bounded_route_cardinality_histograms_and_no_identity_labels():
    metrics = Metrics()
    metrics.observe_http("GET", "/users/{user_id}", 200, 0.1)
    metrics.observe_http("GET", "/health", 200, 0.02)
    output = metrics.render()
    assert 'route="/users/{user_id}"' in output
    assert 'finesse_http_request_duration_seconds_bucket{method="GET",route="/health",le="+Inf"} 1' in output
    assert "# TYPE finesse_http_request_duration_seconds histogram" in output
    assert "status=\"200\"" not in output


def test_local_priority_semaphore_caps_concurrency_and_prioritizes_waiters():
    async def run():
        semaphore = PrioritySemaphore(1)
        order = []
        entered = asyncio.Event()
        async def hold():
            async with semaphore.slot(priority=5):
                order.append("holder")
                entered.set()
                await asyncio.sleep(0.03)
        async def waiter(name, priority):
            await entered.wait()
            async with semaphore.slot(priority=priority):
                order.append(name)
        tasks = [asyncio.create_task(hold())]
        await entered.wait()
        tasks += [asyncio.create_task(waiter("background", 4)),
                  asyncio.create_task(waiter("interactive", 0))]
        await asyncio.gather(*tasks)
        assert order == ["holder", "interactive", "background"]
    asyncio.run(run())
