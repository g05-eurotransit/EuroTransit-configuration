# Networking and Ingress

This document owns Kubernetes networking and ingress behavior for EuroTransit Marketplace.

## Required Rules

- Traefik is the north-south gateway.
- React frontend, Catalog, and Orders are the only public service groups.
- Inventory, Payments, and Notifications are internal-only.
- Keycloak is the cluster/proof OIDC identity provider.
- Protected external APIs must reject unauthenticated traffic before it reaches service pods.
- Service-level authorization remains the responsibility of the application services.
- Payments remains internal-only even though it calls an external provider sandbox/test API.

## To Document

- namespaces;
- Services and IngressRoutes;
- Traefik middleware;
- Keycloak/OIDC middleware or forward-auth integration;
- TLS strategy;
- React frontend route;
- local kind routing and port-forwarding;
- production routing differences.
