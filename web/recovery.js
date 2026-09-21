/* Same-origin durable audio journal. Remove only after server acknowledgement. */
const SpeechRecovery = (() => {
  const opened = new Promise((resolve, reject) => {
    const request = indexedDB.open("speech-audio-recovery", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("captures", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  async function transact(mode, action) {
    const db = await opened;
    return new Promise((resolve, reject) => {
      const tx = db.transaction("captures", mode);
      const req = action(tx.objectStore("captures"));
      tx.oncomplete = () => resolve(req.result);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error("Audio storage failed"));
    });
  }
  return { put: (row) => transact("readwrite", (s) => s.put(row)),
    remove: (id) => transact("readwrite", (s) => s.delete(id)),
    list: () => transact("readonly", (s) => s.getAll()) };
})();
