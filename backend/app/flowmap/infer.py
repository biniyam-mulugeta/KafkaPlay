"""The topic flow map.

An honest graph of how data moves: topics, the consumer groups reading them,
and the topics those groups write to.

A limitation worth stating plainly, because it shapes the whole feature:
**Kafka exposes no API that maps producers to topics.** DescribeProducers
(KIP-664) returns producer IDs and epochs, not client IDs, and broker metrics
break down by client only when JMX is available. So producer edges cannot be
derived from the admin API at all.

Rather than guess, this module draws what it can prove -- group-to-topic edges
from committed offsets, with throughput and lag from the sampler -- and marks
everything else as declared. Declared edges come from `producer_hints` and
`group_output_hints` in cluster config, or from operator annotations. Each
edge says which it is, so nobody mistakes a hint for a measurement.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.clusters.models import ClusterConfig
from app.kafka.errors import KafkaGateError
from app.kafka.gate import KafkaGate
from app.sampler.series import topic_throughput
from app.store.models import FlowEdgeAnnotation


class NodeKind(StrEnum):
    TOPIC = "topic"
    GROUP = "group"
    PRODUCER = "producer"


class EdgeSource(StrEnum):
    OBSERVED = "observed"
    """Derived from broker state: this is measured, not guessed."""

    DECLARED = "declared"
    """From cluster config or an operator annotation."""


class FlowNode(BaseModel):
    id: str
    label: str
    kind: NodeKind
    partitions: int | None = None
    messages_per_second: float | None = None
    lag: int | None = None
    state: str | None = None


class FlowEdge(BaseModel):
    source: str
    target: str
    kind: str
    origin: EdgeSource
    messages_per_second: float | None = None
    lag: int | None = None


class FlowMap(BaseModel):
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    degraded: str | None = None


async def build_flow_map(
    gate: KafkaGate,
    cluster: ClusterConfig,
    engine: Engine,
    *,
    window_minutes: int = 30,
) -> FlowMap:
    flow = FlowMap()
    nodes: dict[str, FlowNode] = {}

    def add(node: FlowNode) -> None:
        if node.id not in nodes:
            nodes[node.id] = node

    try:
        topics = await gate.list_topics(include_internal=False)
    except KafkaGateError as exc:
        flow.degraded = exc.message
        return flow

    for topic in topics:
        throughput = topic_throughput(
            engine, cluster=cluster.name, topic=topic.name, window_minutes=window_minutes
        )
        add(
            FlowNode(
                id=f"topic:{topic.name}",
                label=topic.name,
                kind=NodeKind.TOPIC,
                partitions=topic.partition_count,
                messages_per_second=throughput.average,
            )
        )

    # --- observed: group -> topic, from committed offsets -------------------
    try:
        groups = await gate.list_groups()
    except KafkaGateError:
        groups = []

    for group in groups:
        try:
            lags = await gate.group_lag(group.group_id)
        except KafkaGateError:
            continue
        if not lags:
            continue

        total_lag = sum(lag.lag for lag in lags if lag.lag is not None)
        add(
            FlowNode(
                id=f"group:{group.group_id}",
                label=group.group_id,
                kind=NodeKind.GROUP,
                lag=total_lag,
                state=str(group.state),
            )
        )

        by_topic: dict[str, int] = {}
        for lag in lags:
            by_topic[lag.topic] = by_topic.get(lag.topic, 0) + (lag.lag or 0)

        for topic_name, topic_lag in by_topic.items():
            add(FlowNode(id=f"topic:{topic_name}", label=topic_name, kind=NodeKind.TOPIC))
            flow.edges.append(
                FlowEdge(
                    source=f"topic:{topic_name}",
                    target=f"group:{group.group_id}",
                    kind="consumes",
                    origin=EdgeSource.OBSERVED,
                    lag=topic_lag,
                )
            )

    # --- declared: producers and group outputs ------------------------------
    for client_id, produced in cluster.producer_hints.items():
        add(FlowNode(id=f"producer:{client_id}", label=client_id, kind=NodeKind.PRODUCER))
        for topic_name in produced:
            add(FlowNode(id=f"topic:{topic_name}", label=topic_name, kind=NodeKind.TOPIC))
            flow.edges.append(
                FlowEdge(
                    source=f"producer:{client_id}",
                    target=f"topic:{topic_name}",
                    kind="produces",
                    origin=EdgeSource.DECLARED,
                )
            )

    for group_id, produced in cluster.group_output_hints.items():
        add(FlowNode(id=f"group:{group_id}", label=group_id, kind=NodeKind.GROUP))
        for topic_name in produced:
            add(FlowNode(id=f"topic:{topic_name}", label=topic_name, kind=NodeKind.TOPIC))
            flow.edges.append(
                FlowEdge(
                    source=f"group:{group_id}",
                    target=f"topic:{topic_name}",
                    kind="produces",
                    origin=EdgeSource.DECLARED,
                )
            )

    with Session(engine) as session:
        annotations = session.exec(
            select(FlowEdgeAnnotation).where(FlowEdgeAnnotation.cluster == cluster.name)
        ).all()
    for annotation in annotations:
        flow.edges.append(
            FlowEdge(
                source=annotation.source,
                target=annotation.target,
                kind=annotation.kind,
                origin=EdgeSource.DECLARED,
            )
        )

    flow.nodes = sorted(nodes.values(), key=lambda node: (node.kind, node.label))

    if not any(edge.kind == "produces" for edge in flow.edges):
        flow.notes.append(
            "No producer edges are shown. Kafka exposes no API mapping producers to "
            "topics, so these must be declared with producer_hints in clusters.yaml."
        )

    return flow
