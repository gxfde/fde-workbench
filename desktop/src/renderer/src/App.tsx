import { useEffect } from "react"

import { AuthProvider, useAuth } from "./auth/AuthProvider"
import { BridgePage } from "./bridge/BridgePage"
import { DispatchPage } from "./dispatch/DispatchPage"
import { ChangePasswordPage } from "./auth/ChangePasswordPage"
import { LoginPage } from "./auth/LoginPage"
import { DangerConfirmProvider } from "./common/DangerConfirmProvider"
import { ConfirmProvider } from "./common/ConfirmProvider"
import { RouteErrorBoundary } from "./common/RouteErrorBoundary"
import { Loading, ToastProvider } from "./components/ui"
import { AIExecutionProvider } from "./ai/AIExecutionProvider"
import { DocumentTemplatesPage } from "./documentTemplates/DocumentTemplatesPage"
import { AppShell } from "./layout/AppShell"
import { ModulesPage } from "./modules/ModulesPage"
import { NewProjectPageV2 } from "./projects/NewProjectPageV2"
import { ProjectDetailPage } from "./projects/ProjectDetailPage"
import { ProjectsPage } from "./projects/ProjectsPage"
import {
  authorizedRoute,
  routeHash,
  useHashRoute,
  type AppRoute,
} from "./routing/useHashRoute"
import { TemplatesPage } from "./templates/TemplatesPage"
import { UsersPage } from "./users/UsersPage"
import { AccountPage } from "./account/AccountPage"
import { TaskCenterPage } from "./tasks/TaskCenterPage"
import { HelpPage } from "./help/HelpPage"
import { ExtensionsPage } from "./extensions/ExtensionsPage"
import { LcscToolPage } from "./extensions/LcscToolPage"
import { LcscComparePage } from "./extensions/LcscComparePage"
import { SystemConfigurationPage } from "./system/SystemConfigurationPage"
import { TranslatorPortalPage } from "./translator/TranslatorPortalPage"
import { MetricsReportPage } from "./metrics/MetricsReportPage"
import { PilotReportPage } from "./pilot/PilotReportPage"
import { SimulationLabPage } from "./SimulationLab/SimulationLabPage"

export function App() {
  return (
    <AuthProvider>
      <AIExecutionProvider><DangerConfirmProvider>
        <ToastProvider><ConfirmProvider>
          <AuthenticatedApp />
        </ConfirmProvider></ToastProvider>
      </DangerConfirmProvider></AIExecutionProvider>
    </AuthProvider>
  )
}

function AuthenticatedApp() {
  const { status, user } = useAuth()
  const route = useHashRoute()
  const permittedRoute = user ? authorizedRoute(route, user.role) : route

  useEffect(() => {
    if (user && routeHash(route) !== routeHash(permittedRoute)) {
      window.location.hash = routeHash(permittedRoute)
    }
  }, [permittedRoute, route, user])

  if (status === "loading") {
    return <main className="loading-page"><Loading label="正在加载工作台…" /></main>
  }
  if (status === "unauthenticated" || !user) return <LoginPage />
  if (user.mustChangePassword) return <ChangePasswordPage />
  return (
    <AppShell route={permittedRoute}>
      <RouteErrorBoundary key={routeHash(permittedRoute)}>
        <RoutePage route={permittedRoute} />
      </RouteErrorBoundary>
    </AppShell>
  )
}

function RoutePage({ route }: { route: AppRoute }) {
  if (route.kind === "account") return <AccountPage />
  if (route.kind === "task-center") return <TaskCenterPage />
  if (route.kind === "dispatch")
    return (
      <DispatchPage
        tab={route.tab ?? "pool"}
        onTabChange={(next) => {
          window.location.hash = next === "pool" ? "#dispatch" : `#dispatch/${next}`
        }}
      />
    )
  if (route.kind === "help") return <HelpPage />
  if (route.kind === "simulation") return <SimulationLabPage />
  if (route.kind === "translator") return <TranslatorPortalPage />
  if (route.kind === "metrics") return <MetricsReportPage />
  if (route.kind === "pilot") return <PilotReportPage />
  if (route.kind === "extensions") return route.tool === 'lcsc-compare' ? <LcscComparePage /> : route.tool ? <LcscToolPage key={route.tool} variant={route.tool} /> : <ExtensionsPage initialTab={route.tab} />
  if (route.kind === "users") return <UsersPage />
  if (route.kind === "system-configuration") return <SystemConfigurationPage />
  if (route.kind === "modules") return <ModulesPage />
  if (route.kind === "templates") return <TemplatesPage />
  if (route.kind === "document-templates") return <DocumentTemplatesPage />
  if (route.kind === "projects") return <ProjectsPage />
  if (route.kind === "bridge") return <BridgePage />
  if (route.kind === "new-project") return <NewProjectPageV2 />
  return <ProjectDetailPage projectId={route.projectId} tab={route.tab ?? "overview"} solutionId={route.solution} solutionMode={route.mode} opportunityId={route.opportunity} />
}
