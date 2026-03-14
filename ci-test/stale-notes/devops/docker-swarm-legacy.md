---
date: 2024-03-20
tags: [devops, docker, containers, orchestration]
type: permanent
status: active
actionable: true
---

# Docker Swarm Deployment Guide

Step-by-step guide for deploying microservices to Docker Swarm clusters.

## Setup

```bash
docker swarm init --advertise-addr 192.168.1.100
docker node ls
docker service create --name web --replicas 3 -p 80:80 nginx
```

## Service Discovery

- Services communicate via DNS names within overlay networks
- Docker Swarm routing mesh handles load balancing automatically
- No need for external service mesh — Swarm handles it natively

## Scaling

```bash
docker service scale web=5
docker service update --image nginx:latest web
```

## Why Swarm Over Kubernetes

- Simpler setup — no etcd cluster, no API server configuration
- Built into Docker Engine — zero additional tooling
- Good enough for most workloads under 100 nodes

## Links

- [[kubernetes-migration]]
- [[monitoring-stack]]
