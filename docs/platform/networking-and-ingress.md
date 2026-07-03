# Networking and Ingress

This document owns Kubernetes networking and ingress behavior for EuroTransit Marketplace.

## Required Rules

- Traefik is the north-south gateway.
- Catalog and Orders are the only public service groups.
- Inventory, Payments, and Notifications are internal-only.
- Protected external APIs must reject unauthenticated traffic before it reaches service pods.
- Service-level authorization remains the responsibility of the application services.

## To Document

- namespaces;
- Services and IngressRoutes;
- Traefik middleware;
- TLS strategy;
- local kind routing and port-forwarding;
- production routing differences.
