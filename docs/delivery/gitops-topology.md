# GitOps Topology

This document owns the delivery topology for EuroTransit Marketplace.

**Owner:** Technical Coordinator + Gateway/Security Slice Owner.

## Responsibilities

- Application CI builds immutable images.
- The configuration repository stores Kubernetes desired state.
- ArgoCD reconciles the target cluster from this repository.
- CI must not hold direct cluster credentials.
- The Technical Coordinator + Gateway/Security Slice Owner owns the GitHub Actions workflows, image build/publish automation, configuration-repository update automation, and delivery rollback procedure.

## Required Inputs from Service Owners

- Service build and test commands remain valid.
- Dockerfile or Jib configuration is maintained per service.
- Runtime environment variables are documented.
- Health/readiness behavior is implemented and stable.

## To Document

- repository layout for manifests or Helm/Kustomize;
- image tag update strategy;
- ArgoCD application structure;
- environment promotion model;
- rollback procedure.
