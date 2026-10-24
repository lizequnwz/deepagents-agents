import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Mic, Square } from "lucide-react";
import { api, message } from "./api";

function wav(samples: Float32Array, sampleRate: number) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++)
      view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  return new Blob([view], { type: "audio/wav" });
}

export function VoiceInput({
  disabled,
  onDraft,
  onError,
}: {
  disabled: boolean;
  onDraft: (value: string) => void;
  onError: (value: string) => void;
}) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const capture = useRef<{
    context: AudioContext;
    stream: MediaStream;
    processor: ScriptProcessorNode;
    source: MediaStreamAudioSourceNode;
    samples: Float32Array[];
    timer: ReturnType<typeof setTimeout>;
  } | null>(null);
  function release() {
    const current = capture.current;
    if (!current) return;
    clearTimeout(current.timer);
    current.processor.disconnect();
    current.source.disconnect();
    current.stream.getTracks().forEach((track) => track.stop());
    void current.context.close();
    capture.current = null;
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      release();
    };
  }, []);
  async function start() {
    onError("");
    setBusy(true);
    let stream: MediaStream | undefined;
    let context: AudioContext | undefined;
    try {
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error(
          "Microphone recording is unavailable. Use a secure local browser or type your question.",
        );
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true },
      });
      if (!mounted.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      context = new AudioContext({ sampleRate: 16000 });
      await context.resume();
      if (!mounted.current) {
        stream.getTracks().forEach((track) => track.stop());
        void context.close();
        return;
      }
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const samples: Float32Array[] = [];
      processor.onaudioprocess = (event) =>
        samples.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      source.connect(processor);
      processor.connect(context.destination);
      capture.current = {
        context,
        stream,
        source,
        processor,
        samples,
        timer: setTimeout(() => void stop(), 120000),
      };
      setRecording(true);
    } catch (e) {
      release();
      stream?.getTracks().forEach((track) => track.stop());
      if (context && context.state !== "closed") void context.close();
      if (mounted.current) onError(message(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function stop() {
    const current = capture.current;
    if (!current) return;
    setRecording(false);
    setBusy(true);
    const count = current.samples.reduce((n, s) => n + s.length, 0);
    const samples = new Float32Array(count);
    let offset = 0;
    for (const part of current.samples) {
      samples.set(part, offset);
      offset += part.length;
    }
    const content = wav(samples, current.context.sampleRate);
    release();
    try {
      if (!count) throw new Error("No audio was recorded. Try again.");
      const result = await api<{ text: string }>("/api/transcriptions", {
        method: "POST",
        body: content,
        headers: { "Content-Type": "audio/wav" },
      });
      if (mounted.current) onDraft(result.text);
    } catch (e) {
      if (mounted.current) onError(message(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <button
      type="button"
      className={`icon-button voice-button ${recording ? "recording" : ""}`}
      aria-label={
        recording
          ? "Stop recording"
          : busy
            ? "Transcribing recording"
            : "Record question"
      }
      disabled={(disabled && !recording) || busy}
      onClick={() => void (recording ? stop() : start())}
    >
      {busy ? (
        <LoaderCircle size={16} className="spin" />
      ) : recording ? (
        <Square size={14} />
      ) : (
        <Mic size={17} />
      )}
    </button>
  );
}
