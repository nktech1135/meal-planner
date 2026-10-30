import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { BarcodeResult, FoodSummary } from "../types";
import { MacroLine } from "./common";
import { TrustBadge } from "./TrustBadge";

// The Barcode Detection API isn't in TypeScript's DOM types yet.
interface DetectedBarcode {
  rawValue: string;
}
interface BarcodeDetectorLike {
  detect(source: HTMLVideoElement): Promise<DetectedBarcode[]>;
}
declare global {
  interface Window {
    BarcodeDetector?: new (opts: { formats: string[] }) => BarcodeDetectorLike;
  }
}

const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
const SOURCE_NAMES: Record<string, string> = {
  local: "this app's database",
  usda_fdc: "USDA FoodData Central",
  open_food_facts: "Open Food Facts (crowdsourced, unverified)",
};

/** Start the camera and call onCode once with the first barcode seen. Returns a stop function. */
async function startCamera(video: HTMLVideoElement, onCode: (code: string) => void): Promise<() => void> {
  if (window.BarcodeDetector) {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    video.srcObject = stream;
    await video.play();
    const detector = new window.BarcodeDetector({ formats: FORMATS });
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      try {
        const found = await detector.detect(video);
        if (found.length && !stopped) {
          onCode(found[0].rawValue);
          return;
        }
      } catch {
        // a frame that isn't ready yet; try the next one
      }
      setTimeout(tick, 200);
    };
    tick();
    return () => {
      stopped = true;
      stream.getTracks().forEach((t) => t.stop());
    };
  }
  // Safari and Firefox lack BarcodeDetector: load the ZXing decoder only when it's needed.
  const { BrowserMultiFormatReader } = await import("@zxing/browser");
  const reader = new BrowserMultiFormatReader();
  let done = false;
  const controls = await reader.decodeFromConstraints(
    { video: { facingMode: { ideal: "environment" } }, audio: false },
    video,
    (result) => {
      if (result && !done) {
        done = true;
        onCode(result.getText());
      }
    },
  );
  return () => controls.stop();
}

/** Scan or type a barcode and pick the matching food. */
export function BarcodeScanner({ onPick, onClose }: { onPick: (f: FoodSummary) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [cameraState, setCameraState] = useState<"starting" | "on" | "off" | "unavailable">("starting");
  const [cameraNote, setCameraNote] = useState("");
  const [typed, setTyped] = useState("");
  const [lookup, setLookup] = useState<{ code: string; result?: BarcodeResult; error?: string } | null>(null);

  async function find(code: string) {
    const clean = code.replace(/\D/g, "");
    if (clean.length < 6) {
      setLookup({ code, error: "That doesn't look like a barcode." });
      return;
    }
    setLookup({ code: clean });
    try {
      setLookup({ code: clean, result: await api.lookupBarcode(clean) });
    } catch (e) {
      setLookup({ code: clean, error: e instanceof Error ? e.message : "Lookup failed" });
    }
  }

  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setCameraState("unavailable");
      setCameraNote("The camera only works over HTTPS (or on this computer via localhost). Type the number instead.");
      return;
    }
    startCamera(video.current!, (code) => {
      stop?.();
      setCameraState("off");
      find(code);
    })
      .then((s) => {
        if (cancelled) s();
        else {
          stop = s;
          setCameraState("on");
        }
      })
      .catch((e: unknown) => {
        setCameraState("unavailable");
        setCameraNote(
          e instanceof DOMException && e.name === "NotAllowedError"
            ? "Camera access was blocked. Allow it in your browser, or type the number instead."
            : "No camera available. Type the number instead.",
        );
      });
    return () => {
      cancelled = true;
      stop?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const result = lookup?.result;
  return (
    <section className="card stack-sm barcode-scanner" aria-label="Scan a barcode">
      <div className="row between wrap">
        <h3 className="h-card">Scan a barcode</h3>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Close
        </button>
      </div>
      <video ref={video} className={`barcode-video ${cameraState === "on" ? "" : "hidden"}`} muted playsInline aria-label="Camera preview" />
      {cameraState === "on" && <p className="muted small">Point the camera at the barcode.</p>}
      {cameraState === "starting" && <p className="muted small">Starting the camera…</p>}
      {cameraNote && <p className="muted small">{cameraNote}</p>}
      {/* Not a <form>: the picker is often inside the page's own form, and a nested submit would reach it. */}
      <div className="row wrap" role="group" aria-label="Type a barcode">
        <label className="sr-only" htmlFor="barcode-digits">
          Barcode number
        </label>
        <input
          id="barcode-digits"
          inputMode="numeric"
          placeholder="Or type the barcode number"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              find(typed);
            }
          }}
        />
        <button type="button" className="btn btn-sm" onClick={() => find(typed)}>
          Look up
        </button>
      </div>

      {lookup && !result && !lookup.error && <p className="muted small" role="status">Looking up {lookup.code}…</p>}
      {lookup?.error && <div className="alert alert-error" role="alert">{lookup.error}</div>}
      {result && (
        <div className="stack-sm" role="status">
          {result.foods.length > 0 ? (
            <>
              <p className="small">
                Found <strong>{result.barcode}</strong> in {SOURCE_NAMES[result.found_in ?? "local"]}:
              </p>
              <ul className="pick-list">
                {result.foods.map((f) => (
                  <li key={f.id}>
                    <button type="button" className="pick-item" onClick={() => onPick(f)}>
                      <span className="pick-name">
                        {f.name}
                        {f.brand ? <span className="muted"> · {f.brand}</span> : null}
                      </span>
                      <span className="pick-meta">
                        <TrustBadge level={f.trust_level} />
                      </span>
                      <MacroLine values={f.macros} />
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="small">
              <strong>{result.barcode}</strong> isn't in this app's database or the online sources that are switched on.{" "}
              <Link to={`/foods/new?barcode=${result.barcode}`}>Add it from the label</Link> and it will be found next time.
            </p>
          )}
          {result.errors.map((e) => (
            <p key={e} className="muted small">
              {e}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
