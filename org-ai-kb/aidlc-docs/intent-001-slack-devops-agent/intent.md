# Intent 001 — Slack DevOps Agent Bot

- **Slug:** slack-devops-agent
- **Type:** Greenfield system (new build) with an external integration to study (AWS Knowledge MCP server)

## Verbatim Prompt

> i wanna build slack bot intergration with a devops agent bot conenct to mcp aws-knowledge-mcp-server use our kiro subscription for access llm or slm to answer question of Developer like review architecture or help build solutions for their implement example use lambda api gw and dynamodb

## Summary

Build a Slack bot that acts as a DevOps assistant for developers. When a developer
asks a question in Slack (e.g. "review this architecture", "help me build X with
Lambda + API Gateway + DynamoDB"), the bot routes the request to an LLM/SLM
(accessed via the team's Kiro subscription) and grounds the answer using the
`aws-knowledge-mcp-server` MCP tools (AWS documentation search, regional
availability, etc.). The bot returns architecture reviews and solution guidance
back into the Slack conversation.

### Key capabilities (as stated)
- Slack integration (receive developer questions, post answers)
- DevOps agent backend that connects to the `aws-knowledge-mcp-server` MCP server
- LLM/SLM inference via the existing Kiro subscription
- Use cases: architecture review, solution design help (e.g. serverless patterns
  with Lambda, API Gateway, DynamoDB)

### Open questions to resolve during composition
- How the Kiro subscription is accessed programmatically (API surface)
- Slack app model (Events API + slash commands vs. Socket Mode)
- Hosting/runtime for the agent backend
