package nl.eyevisions.sdrcc.mobile;

import org.junit.Test;
import java.io.IOException;
import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class MarineAudioServiceTest {
    private byte[] header(int rate) {
        byte[] bytes = new byte[44];
        System.arraycopy("RIFF".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, bytes, 0, 4);
        System.arraycopy("WAVE".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, bytes, 8, 4);
        System.arraycopy("fmt ".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, bytes, 12, 4);
        bytes[16] = 16; // PCM fmt chunk
        bytes[20] = 1;  // PCM
        bytes[22] = 1;  // mono
        bytes[24] = (byte) rate;
        bytes[25] = (byte) (rate >>> 8);
        bytes[26] = (byte) (rate >>> 16);
        bytes[27] = (byte) (rate >>> 24);
        bytes[34] = 16; // 16-bit
        System.arraycopy("data".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, bytes, 36, 4);
        return bytes;
    }

    @Test
    public void reassemblesPcm16FramesAcrossOddNetworkReads() {
        MarineAudioService.Pcm16FrameAssembler frames =
                new MarineAudioService.Pcm16FrameAssembler();
        byte[] firstRead = {1, 2, 3};
        int firstCount = frames.alignRead(firstRead, firstRead.length);
        assertEquals(2, firstCount);
        assertArrayEquals(new byte[]{1, 2}, java.util.Arrays.copyOf(firstRead, firstCount));
        assertTrue(frames.hasPendingByte());
        assertEquals(1, frames.readOffset());

        // The next HTTP read starts at offset 1 so the carried byte can occupy byte 0.
        byte[] secondRead = {0, 4, 5, 6};
        int secondCount = frames.alignRead(secondRead, 3);
        assertEquals(4, secondCount);
        assertArrayEquals(new byte[]{3, 4, 5, 6}, java.util.Arrays.copyOf(secondRead, secondCount));
        assertFalse(frames.hasPendingByte());
    }

    @Test
    public void cleanQuietStreamEndReturnsToWaiting() {
        assertEquals("WAITING", MarineAudioService.retryState(true));
    }

    @Test
    public void failedStreamStillShowsReconnect() {
        assertEquals("RECONNECTING", MarineAudioService.retryState(false));
    }

    @Test
    public void readsActualSdrccWavRate() throws IOException {
        assertEquals(16000, MarineAudioService.wavSampleRate(header(16000)));
        assertEquals(8000, MarineAudioService.wavSampleRate(header(8000)));
        assertEquals(48000, MarineAudioService.wavSampleRate(header(48000)));
    }

    @Test(expected = IOException.class)
    public void rejectsMalformedStreamHeader() throws IOException {
        byte[] broken = header(16000);
        broken[8] = 'X';
        MarineAudioService.wavSampleRate(broken);
    }

    @Test(expected = IOException.class)
    public void rejectsUnsupportedRate() throws IOException {
        MarineAudioService.wavSampleRate(header(96000));
    }

    @Test(expected = IOException.class)
    public void rejectsStereoStream() throws IOException {
        byte[] stereo = header(16000);
        stereo[22] = 2;
        MarineAudioService.wavSampleRate(stereo);
    }
}
