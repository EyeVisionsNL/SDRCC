package nl.eyevisions.sdrcc.mobile;

import org.junit.Test;
import java.io.IOException;
import static org.junit.Assert.assertEquals;

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
