// =============================================================================
// Energy Fraud Detection — Azure platform infrastructure (Bicep)
//
// Provisions the Azure resources the demo needs:
//   - Log Analytics + Application Insights (observability / GenAI traces)
//   - Container Apps Environment (hosts the dashboard + voice agent)
//   - Azure AI Foundry (AI Services) account + a chat model deployment
//     (also provides Content Safety / Prompt Shields)
//   - Azure AI Search (energy regulations index)
//
// NOT provisioned here (bring your own / deploy separately):
//   - Azure Databricks workspace + Delta tables + ML model + Genie
//   - The container apps themselves (deploy with `az containerapp up` / azd)
//   - Azure Communication Services (optional, for phone calls)
//   - Microsoft Foundry Agent Service project (for the LangGraph hosted agents)
//
// Deploy:
//   az group create -n <rg> -l swedencentral
//   az deployment group create -g <rg> -f infra/main.bicep -p infra/main.parameters.json
// =============================================================================

@description('Prefix used to name resources (3-12 lowercase alphanumeric).')
@minLength(3)
@maxLength(12)
param namePrefix string = 'energyfraud'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Chat model to deploy on the AI Foundry account (used by the agents).')
param chatModelName string = 'gpt-4.1'

@description('Chat model version.')
param chatModelVersion string = '2025-04-14'

@description('Capacity (tokens-per-minute in thousands) for the chat deployment.')
param chatModelCapacity int = 50

@description('SKU for Azure AI Search.')
@allowed([ 'basic', 'standard' ])
param searchSku string = 'basic'

var suffix = uniqueString(resourceGroup().id)
var logAnalyticsName = '${namePrefix}-log-${suffix}'
var appInsightsName = '${namePrefix}-appi-${suffix}'
var acaEnvName = '${namePrefix}-cae-${suffix}'
var aiFoundryName = '${namePrefix}-aifoundry-${suffix}'
var searchName = '${namePrefix}-search-${suffix}'

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Container Apps Environment (hosts the dashboard + voice agent)
// ---------------------------------------------------------------------------
resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: acaEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Azure AI Foundry (AI Services) + chat model deployment
// Provides the gpt-4.1 model for the agents and Content Safety / Prompt Shields.
// ---------------------------------------------------------------------------
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiFoundryName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: aiFoundryName
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiFoundry
  name: chatModelName
  sku: {
    name: 'GlobalStandard'
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

// ---------------------------------------------------------------------------
// Azure AI Search (energy regulations index)
//   Provisions the service only; the `regulations-policies` index and its
//   documents (real, paraphrased Spanish/EU electricity regulations: Ley
//   24/2013, RD 1955/2000, RD 1110/2007, Directive (EU) 2019/944) are seeded
//   separately after deployment.
// ---------------------------------------------------------------------------
resource search 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: searchName
  location: location
  sku: { name: searchSku }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
}

// ---------------------------------------------------------------------------
// Outputs (use these to configure the apps / .env)
// ---------------------------------------------------------------------------
output containerAppsEnvironmentId string = acaEnv.id
output containerAppsEnvironmentName string = acaEnv.name
output aiFoundryEndpoint string = aiFoundry.properties.endpoint
output aiFoundryName string = aiFoundry.name
output chatDeploymentName string = chatDeployment.name
output contentSafetyEndpoint string = aiFoundry.properties.endpoint
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output logAnalyticsWorkspaceId string = logAnalytics.id
