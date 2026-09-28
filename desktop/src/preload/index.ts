import { contextBridge, ipcRenderer } from "electron"

import {
  IPC_CHANNELS,
  type AuthResult,
  type ApiRequestOptions,
  type ApiResponse,
  type BridgeResult,
  type FdeBridge,
  type LoginInput,
} from "../shared/contracts"

const bridge: FdeBridge = Object.freeze({
  auth: Object.freeze({
    login: (input: LoginInput): Promise<BridgeResult<AuthResult>> =>
      ipcRenderer.invoke(IPC_CHANNELS.authLogin, input),
    refresh: (): Promise<BridgeResult<AuthResult | null>> =>
      ipcRenderer.invoke(IPC_CHANNELS.authRefresh),
    changePassword: (
      accessToken: string,
      currentPassword: string,
      newPassword: string,
    ): Promise<BridgeResult<AuthResult>> =>
      ipcRenderer.invoke(
        IPC_CHANNELS.authChangePassword,
        accessToken,
        currentPassword,
        newPassword,
      ),
    logout: (): Promise<BridgeResult<null>> =>
      ipcRenderer.invoke(IPC_CHANNELS.authLogout),
  }),
  api: Object.freeze({
    request: <T>(
      path: string,
      options: ApiRequestOptions,
    ): Promise<BridgeResult<ApiResponse<T>>> =>
      ipcRenderer.invoke(IPC_CHANNELS.apiRequest, { path, ...options }),
  }),
  app: Object.freeze({
    version: () => ipcRenderer.invoke(IPC_CHANNELS.appVersion),
    openLcscBrowser: (url: string): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.appOpenLcscBrowser, url),
    showLcscDownload: (filename: string): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.appShowLcscDownload, filename),
    copyLcscRunId: (id: string): Promise<void> => ipcRenderer.invoke(IPC_CHANNELS.appCopyLcscRunId, id),
  }),
})

contextBridge.exposeInMainWorld("fde", bridge)
