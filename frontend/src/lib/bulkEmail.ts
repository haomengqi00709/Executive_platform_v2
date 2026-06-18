import { createContext, useContext } from 'react';

/** App-level one-shot signal to resume the bulk-email modal from the task
 * console's "Open" button. requestResume() navigates to the Data page and
 * sets the flag; CrmTab consumes it on mount and clears it immediately, so
 * there is no staleness window. preview.json (server-side) is the source of
 * truth the resumed modal reads — this is just the "reopen now" trigger. */
export interface BulkEmailCtx {
  resumeRequested: boolean;
  requestResume: () => void;
  clearResume: () => void;
}

export const BulkEmailContext = createContext<BulkEmailCtx>({
  resumeRequested: false,
  requestResume: () => {},
  clearResume: () => {},
});

export function useBulkEmail() {
  return useContext(BulkEmailContext);
}
