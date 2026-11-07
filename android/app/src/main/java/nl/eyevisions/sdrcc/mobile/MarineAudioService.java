package nl.eyevisions.sdrcc.mobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * User-started, native foreground listener for the SDRCC PCM16 mono WAV endpoint.
 *
 * The WebView handles station controls and recordings, never background playback.
 * This service does not start/stop SDR receivers. It reconnects only the read-only
 * listening HTTP stream and can be stopped from the app or the notification.
 */
public final class MarineAudioService extends Service {
    public static final String ACTION_START = "nl.eyevisions.sdrcc.mobile.MARINE_AUDIO_START";
    public static final String ACTION_STOP = "nl.eyevisions.sdrcc.mobile.MARINE_AUDIO_STOP";
    public static final String ACTION_STATE = "nl.eyevisions.sdrcc.mobile.MARINE_AUDIO_STATE";
    public static final String EXTRA_URL = "stream_url";
    public static final String EXTRA_VOLUME = "volume";

    private static final String CHANNEL = "sdrcc_marine_audio";
    private static final int NOTIFICATION_ID = 203;
    private static final int CONNECT_TIMEOUT_MS = 9000;
    private static final int READ_TIMEOUT_MS = 19000;
    private final AtomicInteger generation = new AtomicInteger();
    private volatile HttpURLConnection connection;
    private volatile AudioTrack track;
    private PowerManager.WakeLock wakeLock;
    private static volatile boolean listening;
    private static volatile String state = "OFF";

    public static boolean isListening() { return listening; }
    public static String state() { return state; }

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationChannel channel = new NotificationChannel(
                CHANNEL, "SDRCC Marine audio", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Background Marine VHF listening and reconnect status");
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || ACTION_STOP.equals(intent.getAction())) {
            stopListening();
            stopSelf();
            return START_NOT_STICKY;
        }
        if (!ACTION_START.equals(intent.getAction())) return START_NOT_STICKY;
        String address = intent.getStringExtra(EXTRA_URL);
        // Only Activity-validated station URLs may reach here; service is not exported.
        if (address == null || !(address.startsWith("http://") ||
                address.startsWith("https://"))) {
            stopListening();
            stopSelf();
            return START_NOT_STICKY;
        }
        final float volume = Math.max(0f, Math.min(1f, intent.getFloatExtra(EXTRA_VOLUME, .85f)));
        int ticket = generation.incrementAndGet();
        disconnect();
        listening = true;
        setState("CONNECTING");
        startForeground(NOTIFICATION_ID, notification());
        PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (wakeLock == null) {
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SDRCC:MarineVoice");
            wakeLock.setReferenceCounted(false);
        }
        if (!wakeLock.isHeld()) wakeLock.acquire();
        Thread worker = new Thread(() -> listen(address, volume, ticket), "SDRCC-Marine-Audio");
        worker.start();
        return START_NOT_STICKY;
    }

    private Notification notification() {
        String detail;
        switch (state) {
            case "LIVE": detail = "Marine VHF live audio"; break;
            case "WAITING": detail = "Waiting for VHF traffic"; break;
            case "RECONNECTING": detail = "Reconnecting audio stream"; break;
            default: detail = "Connecting to SDRCC";
        }
        Intent open = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent openIntent = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Intent stop = new Intent(this, MarineAudioService.class).setAction(ACTION_STOP);
        PendingIntent stopIntent = PendingIntent.getService(this, 1, stop,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle("SDRCC · Marine Voice")
                .setContentText(detail)
                .setContentIntent(openIntent)
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .setCategory(Notification.CATEGORY_TRANSPORT)
                .addAction(android.R.drawable.ic_media_pause, "Stop", stopIntent)
                .build();
    }

    private void setState(String next) {
        state = next;
        if (!listening && !"OFF".equals(next)) return;
        if (listening) {
            getSystemService(NotificationManager.class).notify(NOTIFICATION_ID, notification());
        }
        sendBroadcast(new Intent(ACTION_STATE).setPackage(getPackageName()));
    }

    private boolean valid(int ticket) {
        return listening && generation.get() == ticket && !Thread.currentThread().isInterrupted();
    }

    private static void readFull(InputStream input, byte[] bytes) throws IOException {
        int offset = 0;
        while (offset < bytes.length) {
            int n = input.read(bytes, offset, bytes.length - offset);
            if (n < 0) throw new EOFException("Incomplete WAV header");
            offset += n;
        }
    }

    static int wavSampleRate(byte[] header) throws IOException {
        if (header.length < 44 ||
                header[0] != 'R' || header[1] != 'I' ||
                header[2] != 'F' || header[3] != 'F' ||
                header[8] != 'W' || header[9] != 'A' ||
                header[10] != 'V' || header[11] != 'E' ||
                header[12] != 'f' || header[13] != 'm' ||
                header[36] != 'd' || header[37] != 'a' ||
                header[38] != 't' || header[39] != 'a' ||
                (header[20] & 255) != 1 || (header[21] & 255) != 0 ||
                (header[22] & 255) != 1 || (header[23] & 255) != 0 ||
                (header[34] & 255) != 16 || (header[35] & 255) != 0) {
            throw new IOException("Unsupported SDRCC WAV stream format");
        }
        int rate = (header[24] & 255) | ((header[25] & 255) << 8) |
                ((header[26] & 255) << 16) | ((header[27] & 255) << 24);
        if (rate < 8000 || rate > 48000) throw new IOException("Invalid WAV rate");
        return rate;
    }

    /** Carries odd PCM16 bytes across arbitrary HTTP read boundaries. */
    static final class Pcm16FrameAssembler {
        private int pendingByte = -1;

        int readOffset() { return pendingByte >= 0 ? 1 : 0; }

        boolean hasPendingByte() { return pendingByte >= 0; }

        int alignRead(byte[] buffer, int count) {
            int aligned = count;
            if (pendingByte >= 0) {
                buffer[0] = (byte) pendingByte;
                aligned++;
                pendingByte = -1;
            }
            if ((aligned & 1) != 0) {
                pendingByte = buffer[aligned - 1] & 255;
                aligned--;
            }
            return aligned;
        }
    }

    static String retryState(boolean cleanEnd) {
        return cleanEnd ? "WAITING" : "RECONNECTING";
    }

    private void listen(String address, float volume, int ticket) {
        int failures = 0;
        while (valid(ticket)) {
            HttpURLConnection active = null;
            AudioTrack audio = null;
            boolean cleanEnd = false;
            try {
                active = (HttpURLConnection) new URL(address).openConnection();
                connection = active;
                active.setConnectTimeout(CONNECT_TIMEOUT_MS);
                active.setReadTimeout(READ_TIMEOUT_MS);
                active.setUseCaches(false);
                active.setRequestProperty("Accept", "audio/wav");
                if (active.getResponseCode() != 200)
                    throw new IOException("Stream HTTP " + active.getResponseCode());
                try (InputStream stream = active.getInputStream()) {
                    byte[] header = new byte[44];
                    readFull(stream, header);
                    int rate = wavSampleRate(header);
                    int minimum = AudioTrack.getMinBufferSize(rate,
                            AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    if (minimum <= 0) throw new IOException("Cannot configure audio output");
                    audio = new AudioTrack.Builder()
                            .setAudioAttributes(new AudioAttributes.Builder()
                                    .setUsage(AudioAttributes.USAGE_MEDIA)
                                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                            .setAudioFormat(new AudioFormat.Builder()
                                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                    .setSampleRate(rate)
                                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                            .setBufferSizeInBytes(Math.max(minimum, rate))
                            .setTransferMode(AudioTrack.MODE_STREAM)
                            .build();
                    if (audio.getState() != AudioTrack.STATE_INITIALIZED)
                        throw new IOException("Audio output unavailable");
                    track = audio;
                    audio.setVolume(volume);
                    audio.play();
                    if (valid(ticket)) setState("WAITING");
                    Pcm16FrameAssembler frames = new Pcm16FrameAssembler();
                    byte[] buffer = new byte[4096];
                    while (valid(ticket)) {
                        int readOffset = frames.readOffset();
                        int count = stream.read(buffer, readOffset, buffer.length - readOffset);
                        if (count < 0) {
                            if (frames.hasPendingByte())
                                throw new EOFException("Incomplete PCM16 sample");
                            cleanEnd = true; // The server closes a quiet stream normally.
                            break;
                        }
                        if (count == 0) continue;
                        int alignedCount = frames.alignRead(buffer, count);
                        if (alignedCount == 0) continue;
                        if ("WAITING".equals(state) || "RECONNECTING".equals(state)) {
                            setState("LIVE");
                        }
                        int offset = 0;
                        while (offset < alignedCount && valid(ticket)) {
                            int wrote = audio.write(buffer, offset, alignedCount - offset);
                            if (wrote <= 0) throw new IOException("Audio output stalled");
                            offset += wrote;
                        }
                    }
                }
                failures = 0; // A successful connection may end normally after VHF silence.
            } catch (IOException | IllegalStateException error) {
                failures++;
            } finally {
                if (track == audio) track = null;
                if (audio != null) {
                    try { audio.pause(); audio.flush(); audio.release(); }
                    catch (IllegalStateException ignored) { audio.release(); }
                }
                if (connection == active) connection = null;
                if (active != null) active.disconnect();
            }
            if (!valid(ticket)) break;
            setState(retryState(cleanEnd));
            long pause = failures >= 5 ? 15000 : Math.min(6000, 1500L * Math.max(1, failures));
            try { Thread.sleep(pause); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); break; }
        }
    }

    private void disconnect() {
        HttpURLConnection old = connection;
        if (old != null) old.disconnect();
        AudioTrack audio = track;
        if (audio != null) {
            try { audio.pause(); } catch (IllegalStateException ignored) { }
        }
    }

    private void stopListening() {
        generation.incrementAndGet();
        listening = false;
        disconnect();
        setState("OFF");
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        stopForeground(true);
    }

    @Override
    public void onDestroy() {
        stopListening();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
