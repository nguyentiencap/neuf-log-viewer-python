# DWS Persistence Unified Guide

**Date**: 2026-05-29  
**Status**: Verified from existing persistence docs  

---

## Table of Contents

1. [Overall Cleanup Strategy](#1-overall-cleanup-strategy)
2. [Known Issues](#2-known-issues)
3. [Storage Paths](#3-storage-paths)
4. [Session Data Cleanup (Time-Based)](#4-session-data-cleanup-time-based)
5. [Transaction Persistence (Event-Driven)](#5-transaction-persistence-event-driven)
6. [Lexmark Integration](#6-lexmark-integration)

---

## 1) Overall Cleanup Strategy

- Session data: time-based cleanup every 600s, retention 3 days.
- Transactions: event-driven remove on job completion.
- Scan files: explicit cleanup when transfer/workflow ends.
- Lexmark does not override cleanup policy; it uses DWS core behavior.

| Data type | Cleanup mechanism | Trigger | Result |
|---|---|---|---|
| Session Data | Time-based | Every 600s | Delete folders older than 3 days |
| Transactions | Event-driven | `RemovePersistenceRequest` after successful post | Delete `{jobUuid}.transaction` file |
| Scan Files | Explicit | `PushScanSuccess` / `PushScanCancel` / framework stop | Delete cache and temp scan files |

### Persistence Chain Index

| Chain | Name                                                           | Entry Event | Section |
|---|----------------------------------------------------------------|---|---|
| **P1** | Session persist                                                | `ISessionEvents.OnLoginEvent` | §4 |
| **P2** | OnLogoutEvent → clear in-memory state (disk files NOT deleted) | `ISessionEvents.OnLogoutEvent` | §4 |
| **P3** | Session scheduled cleanup (disk)                               | `CleanUpTransactionBaseTask.run()` every 600s | §4 |
| **P4** | Scan transaction persistence                                   | `IDeviceJobEvents.Scan.Begin` + `IScanTransferManager.PushScanRequest` | §5 |
| **P5** | Copy transaction persistence                                   | `IDeviceJobEvents.Copy.EscrowRequest` | §5 |
| **P6** | Print transaction persistence                                  | `ITransactionJobPostingProvider.Print.SerializeRequest` | §5 |


## 2) Known Issues

### Issue #1: LostTransaction files are never deleted

**Affected path**: `LostTransaction/{deviceId}/COPY|SCAN|PRINT-{jobUuid}`

**Root cause**:  
When a transaction posting fails after `MAX_RETRYTIMES` (3 retries), `LostTransactionsController` calls `persistLostJob()`, which triggers `PersistLostTransactionRequest`. `TransactionPersistenceHandler.onPersistLostTransactionRequestEvent()` then **renames** (not deletes) the file from `Transaction/{TYPE}/{jobUuid}.transaction` → `LostTransaction/{deviceId}/{TYPE}-{jobUuid}`.

There is **no cleanup mechanism** for the `LostTransaction/` directory:
- No scheduled cleanup task (unlike Session Data which runs every 600s).
- No event-driven deletion (unlike Transaction files which are deleted on `PostResponseSuccess`).
- No TTL or size limit policy.

**Impact**:  
Over time, every failed transaction permanently accumulates a file under `LostTransaction/`. On devices with high transaction failure rates (e.g., prolonged server offline), this can exhaust disk space and potentially impact the entire DWS application.

**Affected flow**: P7.5 — `retryTimes >= 3 → rename transaction to LostTransaction file`

**Code**:
```
PostResponseFailure (retry 1) → PostResponseFailure (retry 2) → PostResponseFailure (retry 3)
  → LostTransactionsController.persistLostJob()
  → TransactionPersistenceHandler.writeLostJob()
      → rename Transaction/COPY|SCAN|PRINT/{jobUuid}.transaction
             → LostTransaction/{deviceId}/COPY|SCAN|PRINT-{jobUuid}
  [file stays on disk indefinitely — no deletion code path exists]
```
---

## 3) Storage Paths

- Session data: `HistoricalSessionData/{ProductType}/{DeviceId}/{FolderTimestamp}/...`
- Transaction data: `Transaction/{COPY|SCAN|PRINT|FAX}/{jobUuid}.transaction`
- Scan cache/data: `ScanTransferManager/cache.ndi`, `ScanMetadataTransferManager/cache.ndi`, `Scan/{ScanSessionId}/...`

- `{PersistenceRoot}/`
  - `HistoricalSessionData/`
    - `{ProductType}/`
      - `{DeviceId}/`
        - `{TimestampFolder}/` — session data files
  - `Transaction/`
    - `COPY/{jobUuid}.transaction`
    - `SCAN/{jobUuid}.transaction`
    - `PRINT/{jobUuid}.transaction`
    - `FAX/{jobUuid}.transaction`
  - `LostTransaction/`
    - `{DeviceId}/COPY-{jobUuid}`
    - `{DeviceId}/SCAN-{jobUuid}`
    - `{DeviceId}/PRINT-{jobUuid}`
  - `ScanTransferManager/cache.ndi`
  - `ScanMetadataTransferManager/cache.ndi`
  - `Scan/{scanSessionId}/` — temp scan image files

---

## 4) Session Data Cleanup (Time-Based)

- Scheduler: `HistoricalSessionManager` runs every 600 seconds.
- Expiration threshold: `now - 72h` (`calendar.add(Calendar.HOUR_OF_DAY, -24 * 3)`).
- Folder expires when `mostRecentTime < expirationDateTime`.
- This is not FIFO/LRU.

**File lifecycle:**
- Files created: `HistoricalSessionData/{ProductType}/{DeviceId}/{timestamp}/...` — written on `PersistHistoricalSessionDataRequest` (triggered on login / account / accounting form / workflow / escrow events)
- Files NOT deleted on logout: disk files are **not removed** on logout — only in-memory state is cleared (see logout flow below)
- Files deleted: `HistoricalSessionData/{ProductType}/{DeviceId}/{timestamp}/` — deleted by scheduled task every 600s if `mostRecentTime < now - 72h`
- Parent device root folder is also removed if it becomes empty after cleanup

### Event chain P1 — Session persist (login → P1.5 write session data to disk)

```
P1.1 — Login / account / workflow / escrow event → post SerializeTransactionSessionBaseRequest
──────────────────────────────────────────────────────────────────────────────
ISessionEvents.OnLoginEvent
  → HistoricalSessionManager.onEvent(OnLoginEvent)                        [HistoricalSessionManager.java:326]
      → processEvent(OnLoginEvent)                                         [HistoricalSessionManager.java:1073]
          → updateFakeJobForTransactionBase(...)                           [HistoricalSessionManager.java:956]
              → addIntoMostRecentSessionIds(session)                       [HistoricalSessionManager.java:999]
                  [track sessionId in most-recent list (max 10)]
              → getFakeCopyJob() or getFakeScanJob()                       [create placeholder job carrying session context]
              → post SerializeTransactionSessionBaseRequest                 [→ continue to P1.2]

IAccountEvents.LoginWithAccount  (optional, fired when account is selected)
  → HistoricalSessionManager.onEvent(LoginWithAccount)                    [HistoricalSessionManager.java:349]
      → processEvent(LoginWithAccount)                                     [HistoricalSessionManager.java:360]
          → historicalSessionManagerStateProvider.setDeviceAccount(account)
          → updateFakeJobForTransactionBase(...)                           [HistoricalSessionManager.java:386]
              → post SerializeTransactionSessionBaseRequest                 [→ continue to P1.2]

IAccountingCodeSessionEvents.LoginWithAccountingForm  (optional, fired when accounting form is submitted)
  → HistoricalSessionManager.onEvent(LoginWithAccountingForm)             [HistoricalSessionManager.java:392]
      → processEvent(LoginWithAccountingForm)                             [HistoricalSessionManager.java:403]
          → historicalSessionManagerStateProvider.setDeviceAccountingForm(accountingForm)
          → updateFakeJobForTransactionBase(...)                           [HistoricalSessionManager.java:426]
              → post SerializeTransactionSessionBaseRequest                 [→ continue to P1.2]

IWorkflowEvents.BeginWorkflow / EndWorkflow  (fired when a workflow starts or ends)
  → HistoricalSessionManager.onEvent(BeginWorkflow)                       [HistoricalSessionManager.java:613]
  → HistoricalSessionManager.onEvent(EndWorkflow)                         [HistoricalSessionManager.java:653]
      → processEvent(BeginWorkflow)                                        [HistoricalSessionManager.java:624]
      → processEvent(EndWorkflow)                                          [HistoricalSessionManager.java:664]
          → historicalSessionManagerStateProvider.setDeviceWorkflow(workflow) / removeDeviceWorkflow()
          → updateFakeJobForTransactionBase(...)                           [HistoricalSessionManager.java:647 / 686]
              → post SerializeTransactionSessionBaseRequest                 [→ continue to P1.2]

Copy.EscrowResponse  (fired after copy escrow pre-authorization; carries escrowToken + copyOemJobId)
  → HistoricalSessionManager.onEvent(EscrowResponse)                      [HistoricalSessionManager.java:890]
      → processEvent(EscrowResponse)                                       [HistoricalSessionManager.java:901]
          → updateFakeJobForTransactionBase(..., referencedJobId=copyOemJobId, escrowToken)  [HistoricalSessionManager.java:941]
              → post SerializeTransactionSessionBaseRequest                [→ continue to P1.2]


P1.2 — SerializeTransactionSessionBaseRequest → posting provider serializes transaction
──────────────────────────────────────────────────────────────────────────────
SerializeTransactionSessionBaseRequest
  → EQ: TransactionJobPostingProvider.onEvent(SerializeTransactionSessionBaseRequest)  [EQ TransactionJobPostingProvider.java:143]
      → mapScanTransaction() or mapCopyTransaction()                       [EQ TransactionJobPostingProvider.java:937 / 746]
      → post SerializeTransactionSessionBaseResponseSuccess                [→ continue to P1.3]
  → OM: OutputManagerTransactionJobPostingProvider.onEvent(SerializeTransactionSessionBaseRequest)  [OM OutputManagerTransactionJobPostingProvider.java:224]
      → mapCopyTransaction() or mapScanTransaction()                       [OM OutputManagerTransactionJobPostingProvider.java:232 / 236]
      → [on success] post SerializeTransactionSessionBaseResponseSuccess   [→ continue to P1.3]
      → [on failure] post SerializeTransactionSessionBaseResponseFailure


P1.3 — SerializeTransactionSessionBaseResponseSuccess → optional time sync
──────────────────────────────────────────────────────────────────────────────
SerializeTransactionSessionBaseResponseSuccess
  → HistoricalSessionManager.onEvent(SerializeTransactionSessionBaseResponseSuccess)   [HistoricalSessionManager.java:432]
      → processEvent(SerializeTransactionSessionBaseResponseSuccess)       [HistoricalSessionManager.java:443]
          [if IDeviceTimeSyncController present]
              → post DeviceConvertServerTimeRequest                        [convert DWS server time to device local time]
          [else]
              → storeTransactionBase(event, null)                         [HistoricalSessionManager.java:455 → skip to P1.4]

DeviceConvertServerTimeResponseSuccess  (only when IDeviceTimeSyncController wired in)
  → HistoricalSessionManager.onEvent(DeviceConvertServerTimeResponseSuccess)  [HistoricalSessionManager.java:539]
      → processEvent(DeviceConvertServerTimeResponseSuccess)               [HistoricalSessionManager.java:550]
          → storeTransactionBase(event, convertedTime)                    [HistoricalSessionManager.java:560 → continue to P1.4]


P1.4 — storeTransactionBase() → add session data to in-memory map
──────────────────────────────────────────────────────────────────────────────
storeTransactionBase()                                                     [HistoricalSessionManager.java:459]
  → new HistoricalSessionData(sessionId, transaction, referencedJobId, escrowToken)
  → historicalSessionDataMap.put(finalDateTime, historicalSessionData)     [add to in-memory NavigableMap<Date, IHistoricalSessionData>]
  → historicalSessionManagerStateProvider.setHistoricalSessionData(...)
  → persistHistoricalSessionData()                                         [HistoricalSessionManager.java:504]
      → post PersistHistoricalSessionDataRequest                           [→ continue to P1.5]


P1.5 — PersistHistoricalSessionDataRequest → write session data to disk
──────────────────────────────────────────────────────────────────────────────
PersistHistoricalSessionDataRequest
  → HistoricalSessionDataPersistenceHandler.onEvent(PersistHistoricalSessionDataRequest)  [HistoricalSessionDataPersistenceHandler.java:135]
      → onPersistRequestEvent()                                            [HistoricalSessionDataPersistenceHandler.java:193]
          → persistenceFactory.createFile(HistoricalSessionData/{ProductType}/{DeviceId}/{timestamp}/...)
          → [write session data to disk]
          → post PersistHistoricalSessionDataResponse
              [no production subscriber — terminal event, used only in tests for verification]
```

### Event chain P2 — OnLogoutEvent → clear in-memory state (disk files NOT deleted)

```
P2.1 — OnLogoutEvent → clear in-memory state (disk files NOT deleted)
──────────────────────────────────────────────────────────────────────────────
ISessionEvents.OnLogoutEvent
  → HistoricalSessionManager.onEvent(OnLogoutEvent)                       [HistoricalSessionManager.java:862]
      → processEvent(OnLogoutEvent)                                        [HistoricalSessionManager.java:873]
          → removeSessionEntries(deviceInstance)                           [HistoricalSessionManager.java:1174]
              → historicalSessionManagerStateProvider.removeDeviceAccount()
              → historicalSessionManagerStateProvider.removeDeviceWorkflow()
              → historicalSessionManagerStateProvider.removeDeviceAccountingForm()
              → historicalSessionManagerStateProvider.removeDeviceScanFormWithEvents()
              → historicalSessionManagerStateProvider.removeDeviceNEUFScanSettingsForm()
              → removeFromMostRecentSessions()
                  [if mostRecentSessionIds.size() > 10]
                      → remove oldest sessionId from list
                      → remove corresponding entries from in-memory historicalSessionDataMap
                  [disk files are NOT deleted here — only in-memory state is cleared]
```

### Event chain P3 — Session scheduled cleanup (time-based disk deletion every 600s)

```
P3.1 — Framework start → schedule cleanup task every 600s
──────────────────────────────────────────────────────────────────────────────
Framework.onFrameworkStarted()
  → HistoricalSessionManager.onFrameworkStarted()                         [HistoricalSessionManager.java:143]
      → scheduledThreadPool.scheduleAtFixedRate(CleanUpTransactionBaseTask, 600s, 600s)  [HistoricalSessionManager.java:150]


P3.2 — Every 600s: compute expiration time (now - 72h) → post remove request per device
──────────────────────────────────────────────────────────────────────────────
[Every 600 seconds]
CleanUpTransactionBaseTask.run()
  → post OnClearHistoricalRecordsEventWrapper

OnClearHistoricalRecordsEventWrapper
  → HistoricalSessionManager.onEvent(OnClearHistoricalRecordsEventWrapper)  [HistoricalSessionManager.java:277]
      → processEvent(OnClearHistoricalRecordsEventWrapper)                 [HistoricalSessionManager.java:288]
          → clearTransactionBaseRecords(deviceInstance)                    [HistoricalSessionManager.java:1128]
              → calendar.add(HOUR_OF_DAY, -24 * 3)                        [timeOfExpiration = now - 72h]
              → for each device with session data:
                  → currentDeviceInstancesForPersistentRemoval.add(deviceInstance)
              → postPersistenceRemoveRequest(timeOfExpiration)             [HistoricalSessionManager.java:1156]
                  → currentDeviceInstancesForPersistentRemoval.remove(0)  [process one device at a time]
                  → post RemoveHistoricalSessionDataPersistenceRequest     [→ continue to P3.3]


P3.3 — RemoveHistoricalSessionDataPersistenceRequest → scan & delete expired folders
──────────────────────────────────────────────────────────────────────────────
RemoveHistoricalSessionDataPersistenceRequest
  → HistoricalSessionDataPersistenceHandler.onEvent(RemoveHistoricalSessionDataPersistenceRequest)  [HistoricalSessionDataPersistenceHandler.java:147]
      → onRemovePersistenceRequestEvent()                                  [HistoricalSessionDataPersistenceHandler.java:416]
          → persistenceFactory.createFile(HistoricalSessionData/{ProductType}/{DeviceId})
          → for each folder in device persistence root:
              → persistenceFolderExpired(expirationDateTime, folderName)  [HistoricalSessionDataPersistenceHandler.java:1211]
                  → read sessionInfo file from folder                      [format: "{sessionIds}_{count}_{mostRecentTime}"]
                  → parse mostRecentTimeInMilliSeconds
                  [if mostRecentTime < expirationDateTime]
                      → expired = true
          [if expired]
              → removePersistenceFolder()                                  [delete all files in folder, then delete folder]
          [if any folder was deleted]
              → removePersistenceFolder(deviceRootPersistenceFolder)      [remove empty parent folder if applicable]
          → post RemoveHistoricalSessionDataPersistenceResponse
```

---

## 5) Transaction Persistence (Event-Driven)

- Supported job types: Copy, Scan, Print, Fax.
- Active jobs stored in memory map (`mapRunTimeJobs`).
- Background task writes active jobs every 5 seconds.
- `RemovePersistenceRequest` is sent only after **transaction is successfully posted to business system**, not simply when the device job ends.
  - Triggered via `TransactionPersistenceController.deletePeristedJob()`.
  - For Scan: `ScanPersistenceController.onScanPostResponseSuccessEvent()` → `deletePeristedJob()`.
  - For Copy/Print: `TransactionJobPostingProvider.onEventAsync(*.PostRequest)` → post to server → on success → `deletePeristedJob()`.

> **Note**: Fax job type is listed in storage paths but its event chain is not yet documented here.

### Event chain per job type

**Scan (P4 + P7):**
> Files created:
> - `Transaction/SCAN/{jobUuid}.transaction` — transaction data, written every 5s, deleted on post success
> - `ScanTransferManager/cache.ndi` — transfer recovery cache, deleted on `PushScanSuccess`/`PushScanCancel`
> - `ScanMetadataTransferManager/cache.ndi` — metadata transfer cache, deleted on metadata transfer complete
> - `Scan/{scanSessionId}/...` — scan image files, deleted on workflow end / `onFrameworkStopping()`
> - `LostTransaction/{deviceId}/SCAN-{jobUuid}` — created only if posting fails after 3 retries
```
P4.1 — Scan.Begin → add transaction to in-memory map
──────────────────────────────────────────────────────────────────────────────
IDeviceJobEvents.Scan.Begin
  → ScanPersistenceController.onScanBeginEvent()                          [ScanPersistenceController.java:45]
      → mapRunTimeJobs.put(jobUuid, transaction)                          [add transaction to memory map]


P4.2 — Scan.Update → update transaction state in memory (repeats)
──────────────────────────────────────────────────────────────────────────────
IDeviceJobEvents.Scan.Update (repeat)
  → ScanPersistenceController.onScanUpdateEvent()                         [ScanPersistenceController.java:83]
      → mapRunTimeJobs.replace(jobUuid, transaction)                      [update transaction state in memory]


P4.3 — Scan.SerializeEndSuccessRequest → write transaction to disk
──────────────────────────────────────────────────────────────────────────────
IDeviceJobEvents.Scan.SerializeEndSuccessRequest
  → ScanPersistenceController.onScanSerializeEndSuccessResponseSuccessEvent()  [ScanPersistenceController.java:210]
  → TransactionPersistenceController.persistJob()                         [TransactionPersistenceController.java:228]
  → post ITransactionManager.Scan.PersistRequest
  → TransactionPersistenceHandler.onEvent(Scan.PersistRequest)            [TransactionPersistenceHandler.java:149]
      → onPersistRequestEvent()                                            [TransactionPersistenceHandler.java:270]
          → mapRunTimeJobs.put(jobUuid, transaction)                      [ensure job tracked in memory — TransactionPersistenceHandler.java:282]
          → persistenceFactory.createFile(Transaction/SCAN/{jobUuid}.transaction)
          → write transaction to disk                                      [background task flushes every 5s — TransactionPersistenceTask:100]
  → post ITransactionManager.Scan.PersistSuccess
  → [posting to backend → continue to P7.1]


P4.4 — [parallel] PushScanRequest → write cache.ndi + start file upload
──────────────────────────────────────────────────────────────────────────────
[--- scan file transfer runs in parallel with P4.1–P4.3 above ---]
IScanTransferManager.PushScanRequest
  → ScanTransferManager.onEventAsync(PushScanRequest)                     [ScanTransferManager.java:57]
      → validateRequest() + addManagerRequest()                           [ScanTransferManager.java:131 / 148]
      → persistenceFactory.createFile(ScanTransferManager/cache.ndi)      [persistManagerRequests — ScanTransferManager.java:162]
  → [scan pages transfer in progress]


P4.5 — [parallel] Transfer result → delete cache files
──────────────────────────────────────────────────────────────────────────────
  [on transfer success]
  → IScanTransferManager.PushScanSuccess
      → ScanTransferManager.onEventAsync(PushScanSuccess)                 [ScanTransferManager.java:85]
          → checkManagerRequestState()
          → delete ScanTransferManager/cache.ndi
          → delete ScanMetadataTransferManager/cache.ndi
  [on transfer cancel]
  → IScanTransferManager.PushScanCancel
      → ScanTransferManager.onEventAsync(PushScanCancel)                  [ScanTransferManager.java:91]
          → delete cache files
  [on framework stopping]
  → ScanManager.onFrameworkStopping()
      → scanStateController.cleanup()
          → delete all temp scan files under Scan/{scanSessionId}/
[--- end parallel scan file transfer ---]


P4.6 — Scan.PostRequest → post transaction to backend (→ then P7)
──────────────────────────────────────────────────────────────────────────────
ITransactionJobPostingProvider.Scan.PostRequest
  [EQ - Equitrac]
  → NEUF-Equitrac TransactionJobPostingProvider.onEventAsync(Scan.PostRequest)  [EQ TransactionJobPostingProvider.java:436]
      → WedpUtils.getProtocol()
      → container.getTransaction()
      → postWedpTransaction()
          → wedpProtocol.transactionPostDeviceJob(toPost)                 [EQ TransactionJobPostingProvider.java:500]
      → [on success] bus.post(Scan.PostResponseSuccess)                   [→ continue to P7.2]
      → [on failure: ServerOffline/Timeout/CommunicationLayerException]
          → bus.post(Scan.PostResponseFailure)                            [→ continue to P7.3]
```

**Copy (P5 + P7):**
> Files created:
> - `Transaction/COPY/{jobUuid}.transaction` — transaction data, written every 5s, deleted on post success
> - `LostTransaction/{deviceId}/COPY-{jobUuid}` — created only if posting fails after 3 retries
```
P5.1 — Copy.EscrowRequest → serialize + write transaction to disk
──────────────────────────────────────────────────────────────────────────────
IDeviceJoblogManager.OnJobLogEvent
  → [create IDeviceCopyJob]
IDeviceJobEvents.Copy.EscrowRequest
  → EQ: TransactionJobPostingProvider.onEventAsync(Copy.EscrowRequest)    [EQ TransactionJobPostingProvider.java:179]
      → mapCopyTransaction()                                               [EQ TransactionJobPostingProvider.java:746]
      → TransactionPersistenceController.persistJob()                     [TransactionPersistenceController.java:228]
      → post ITransactionManager.Copy.PersistRequest
      → TransactionPersistenceHandler.onEvent(Copy.PersistRequest)        [TransactionPersistenceHandler.java:130]
          → onPersistRequestEvent()                                        [TransactionPersistenceHandler.java:270]
              → mapRunTimeJobs.put(jobUuid, container)                    [TransactionPersistenceHandler.java:282]
              → [background task flushes every 5s]                        [write to disk: Transaction/COPY/{jobUuid}.transaction]
      → post ITransactionManager.Copy.PersistResponseSuccess
      → transactionPostEscrowDeviceJob()
  → IDeviceJobEvents.Copy.EscrowResponse
  → [Copy job completes on device]


P5.2 — Copy.PostRequest → post transaction to backend (→ then P7)
──────────────────────────────────────────────────────────────────────────────
ITransactionJobPostingProvider.Copy.PostRequest
  [EQ - Equitrac]
  → NEUF-Equitrac TransactionJobPostingProvider.onEventAsync(Copy.PostRequest)  [EQ TransactionJobPostingProvider.java:298]
      → WedpUtils.getProtocol()
      → container.getTransaction()
      → [if no escrow token] wedpProtocol.transactionPostDeviceJob(toPost)          [EQ TransactionJobPostingProvider.java:321]
      → [if escrow token]    wedpProtocol.transactionPostReconcileDeviceJob(toPost, escrowToken)  [EQ TransactionJobPostingProvider.java:323]
      → [on success] bus.post(Copy.PostResponseSuccess)                   [→ continue to P7.2]
      → [on failure: ServerOffline/Timeout/CommunicationLayerException]
          → bus.post(Copy.PostResponseFailure)                            [→ continue to P7.3]
```

**Print (P6 + P7):**
> Files created:
> - `Transaction/PRINT/{jobUuid}.transaction` — transaction data, written every 5s, deleted on post success
> - `LostTransaction/{deviceId}/PRINT-{jobUuid}` — created only if posting fails after 3 retries
```
P6.1 — Print.SerializeRequest → serialize + write transaction to disk
──────────────────────────────────────────────────────────────────────────────
HTTP POST job log → PluginEventServlet.doPost()
  → IDeviceJoblogManager.OnJobLogEvent
      → [create IDevicePrintJob]
ITransactionJobPostingProvider.Print.SerializeRequest
  → EQ: TransactionJobPostingProvider.onEvent(Print.SerializeRequest)     [EQ TransactionJobPostingProvider.java:533]
      → mapPrintTransaction()                                              [EQ TransactionJobPostingProvider.java:832]
      → TransactionPersistenceController.persistJob()                     [TransactionPersistenceController.java:228]
      → post ITransactionManager.Print.PersistRequest
      → TransactionPersistenceHandler.onEvent(Print.PersistRequest)       [TransactionPersistenceHandler.java:167]
          → onPersistRequestEvent()                                        [TransactionPersistenceHandler.java:270]
              → mapRunTimeJobs.put(jobUuid, container)                    [TransactionPersistenceHandler.java:282]
              → [background task flushes every 5s]                        [write to disk: Transaction/PRINT/{jobUuid}.transaction]
      → post ITransactionManager.Print.PersistResponseSuccess


P6.2 — Print.PostRequest → post transaction to backend (→ then P7)
──────────────────────────────────────────────────────────────────────────────
ITransactionJobPostingProvider.Print.PostRequest
  [EQ - Equitrac]
  → NEUF-Equitrac TransactionJobPostingProvider.onEventAsync(Print.PostRequest)  [EQ TransactionJobPostingProvider.java:367]
      → WedpUtils.getProtocol()
      → container.getTransaction()
      → [if overrideUuid]    wedpProtocol.transactionPostReconcileDeviceJob(toPost, overrideUuid)  [EQ TransactionJobPostingProvider.java:388]
      → [if no overrideUuid] wedpProtocol.transactionPostDeviceJob(toPost)  [EQ TransactionJobPostingProvider.java:390]
      → [on success] bus.post(Print.PostResponseSuccess)                  [→ continue to P7.2]
      → [on failure: ServerOffline/Timeout/CommunicationLayerException]
          → bus.post(Print.PostResponseFailure)                           [→ continue to P7.3]
```

### Common shared flow: PostRequest flow P7 — PostRequest / retry / lost transaction (EQ / OM / Success / Failure)

> Applies to **Scan** (from P4.6), **Copy** (from P5.2), **Print** (from P6.2).

```
P7.1 — {Scan/Copy/Print}.PostRequest → EQ/OM posts to backend server
──────────────────────────────────────────────────────────────────────────────
ITransactionJobPostingProvider.{Scan/Copy/Print}.PostRequest
  [OM - OutputManager]
  → NEUF-OutputManager OutputManagerTransactionJobPostingProvider.onEventAsync(Copy.PostRequest)    [OM OutputManagerTransactionJobPostingProvider.java:140]
  → NEUF-OutputManager OutputManagerTransactionJobPostingProvider.onEventAsync(Scan.PostRequest)    [OM OutputManagerTransactionJobPostingProvider.java:178]
  → NEUF-OutputManager OutputManagerTransactionJobPostingProvider.onEventAsync(Print.PostRequest)   [OM OutputManagerTransactionJobPostingProvider.java:159]
      → container.getTransaction()
      → converter.toXml(OutputDocumentStatuses.class, transaction)
      → outputManagerService.setJobStatusesWithXml(deviceInstance, xTransaction)  [OM OutputManagerTransactionJobPostingProvider.java:150/188/169]
      → [on success] bus.post({Scan/Copy/Print}.PostResponseSuccess)      [→ continue to P7.2]
      → [on failure] bus.post({Scan/Copy/Print}.PostResponseFailure)      [→ continue to P7.3]


P7.2 — PostResponseSuccess → delete persisted transaction file
──────────────────────────────────────────────────────────────────────────────
  [on {Scan/Copy/Print}.PostResponseSuccess]
  → ScanPersistenceController.onScanPostResponseSuccessEvent()            [ScanPersistenceController.java:339]
  → CopyPersistenceController.onCopyPostResponseSuccessEvent()            [CopyPersistenceController.java:245]
  → PrintPersistenceController.onPrintPostResponseSuccessEvent()          [PrintPersistenceController.java:245]
      → transactionRecords.getPostRequestByRequestId()
      → post ITransactionEvents.{Scan/Copy/Print}.PostSuccess
      → TransactionPersistenceController.deletePeristedJob()              [TransactionPersistenceController.java:268]
      → post ITransactionManager.{Scan/Copy/Print}.RemovePersistenceRequest
      → TransactionPersistenceHandler.onEventAsync({Scan/Copy/Print}.RemovePersistenceRequest)
          [Scan:  TransactionPersistenceHandler.java:155]
          [Copy:  TransactionPersistenceHandler.java:137]
          [Print: TransactionPersistenceHandler.java:173]
          → onRemovePersistenceRequestEvent()                             [TransactionPersistenceHandler.java:321]
              → mapRunTimeJobs.remove(jobUuid)                            [TransactionPersistenceHandler.java:333]
              → removePersistedJob(jobUuid)                               [TransactionPersistenceHandler.java:561]
                  → persistenceFactory.createFile(Transaction/SCAN|COPY|PRINT/{jobUuid}.transaction)
                  → if (persistenceFile.exists()) { persistenceFile.delete() }
          → post ITransactionManager.{Scan/Copy/Print}.RemovePersistenceSuccess


P7.3 — PostResponseFailure (1st attempt) → hand off to LostTransactionsController for retry
──────────────────────────────────────────────────────────────────────────────
  [on {Scan/Copy/Print}.PostResponseFailure — first post, handled by {Scan/Copy/Print}PersistenceController]
  → ScanPersistenceController (handled via LostTransactionsController)
  → CopyPersistenceController.onCopyPostResponseFailureEvent()            [CopyPersistenceController.java:289]
  → PrintPersistenceController.onPrintPostResponseFailureEvent()          [PrintPersistenceController.java:288]
      → transactionRecords.getPostRequestByRequestId()
      → post ITransactionManager.{Scan/Copy/Print}.RePostRequest          [LostTransactionsController listens]
      → post ITransactionEvents.{Scan/Copy/Print}.PostFailed
          [Copy — Android only] AndroidToastsManager.onEvent(ITransactionEvents.Copy.PostFailed)
              → postPlatformBannerMessage(...)
          [Scan, Print] no subscriber in core
      → transactionRecords.remove(postRequestId, jobUuid)
  → LostTransactionsController.onEvent({Scan/Copy/Print}.RePostRequest)
      [Scan:  LostTransactionsController.java:337]
      [Copy:  LostTransactionsController.java:318]
      [Print: LostTransactionsController.java:356]
      → onRepostRequest()                                                  [LostTransactionsController.java:394]
          → create new ITransactionJobPostingProvider.{Scan/Copy/Print}.PostRequest
          → transactionRecords.setRequestIdRetryTimes(postRequestId, 0)
          → scheduleNextPosting(TransactionRepostingTask)                  [LostTransactionsController.java:204 → back to P7.1]


P7.4 — Retry PostResponseFailure (retryTimes < 3) → schedule next retry
──────────────────────────────────────────────────────────────────────────────
  [on retry {Scan/Copy/Print}.PostResponseFailure — retries handled by LostTransactionsController]
  → LostTransactionsController.onEvent({Scan/Copy/Print}.PostResponseFailure)
      [Scan:  LostTransactionsController.java:350]
      [Copy:  LostTransactionsController.java:331]
      [Print: LostTransactionsController.java:369]
      → onPostResponseFailureEvent()                                       [LostTransactionsController.java:524]
          → retryTimes = currentRetry + 1
          → [if bOffline] keep retryTimes unchanged
          → [if retryTimes < 3] scheduleNextPosting(TransactionRepostingTask)  [LostTransactionsController.java:614 → back to P7.1]


P7.5 — retryTimes >= 3 → rename transaction to LostTransaction file
──────────────────────────────────────────────────────────────────────────────
          → [if retryTimes >= 3]
              → persistLostJob()                                           [LostTransactionsController.java:220]
              → post ITransactionManager.{Scan/Copy/Print}.PersistLostTransactionRequest
              → TransactionPersistenceHandler.onEventAsync({Scan/Copy/Print}.PersistLostTransactionRequest)
                  [Scan:  TransactionPersistenceHandler.java:161]
                  [Copy:  TransactionPersistenceHandler.java:143]
                  [Print: TransactionPersistenceHandler.java:179]
                  → onPersistLostTransactionRequestEvent()                 [TransactionPersistenceHandler.java:378]
                      → writeLostJob()                                     [TransactionPersistenceHandler.java:597]
                          → rename Transaction/SCAN|COPY|PRINT/{jobUuid}.transaction
                                → LostTransaction/{deviceId}/SCAN|COPY|PRINT-{jobUuid}
                      → mapRunTimeJobs.remove(jobUuid) or mapUnsentTransactions.remove(jobUuid)
                                                                           [TransactionPersistenceHandler.java:390 / 396]
                      → post ITransactionManager.{Scan/Copy/Print}.PersistLostTransactionSuccess
           → post ITransactionEvents.{Scan/Copy/Print}.PostFailed
              [Copy — Android only] AndroidToastsManager.onEvent(ITransactionEvents.Copy.PostFailed)
                  → postPlatformBannerMessage(...)
              [Scan, Print] no subscriber in core
```

---

## 6) Lexmark Integration

- `NEUF-LexmarkUC-Platform/.../PersistenceFactory.java` is a wrapper implementation of `IPersistenceFactory`.
- It handles file creation and recursive delete utility.
- Cleanup policy remains from DWS core handlers (session/transaction/scan).

- `Lexmark PersistenceFactory` *(createFile / streams / deleteFile)*
  - implements `IPersistenceFactory` contract
    - used by **DWS Core Handlers**:
      - `HistoricalSessionManager` + `HistoricalSessionDataPersistenceHandler` → 3-day time-based cleanup
      - `TransactionPersistenceHandler` → event-based cleanup
      - `ScanTransferManager` → explicit scan cleanup

---
