package nl.eyevisions.sdrcc.mobile;

import android.content.Context;
import android.animation.ValueAnimator;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.SweepGradient;
import android.os.SystemClock;
import android.view.View;

/** Native radar display for the branded connection screen. */
public final class RadarView extends View {
    private static final int ACCENT = 0xFF72D8B3;
    private static final float[] TARGET_BEARINGS = {-48f, 18f, 72f, 142f, 224f};
    private static final float[] TARGET_RANGES = {.57f, .73f, .44f, .78f, .36f};

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path sweepWedge = new Path();
    private final Matrix sweepMatrix = new Matrix();
    private final RectF radarBounds = new RectF();
    private float angle = 220f;
    private float radius;
    private long lastFrameTime;
    private Shader fieldShader;
    private SweepGradient sweepShader;

    public RadarView(Context context) {
        super(context);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        float cx = width / 2f;
        float cy = height / 2f;
        radius = Math.max(0f, Math.min(cx, cy) - dp(18));
        radarBounds.set(cx - radius, cy - radius, cx + radius, cy + radius);
        fieldShader = new RadialGradient(cx, cy, radius,
                new int[]{0x263C8D79, 0x10203D42, 0x0015252D}, null,
                Shader.TileMode.CLAMP);
        sweepShader = new SweepGradient(cx, cy,
                new int[]{0x0072D8B3, 0x0072D8B3, 0x1672D8B3,
                        0x4872D8B3, 0x0072D8B3},
                new float[]{0f, .81f, .90f, .97f, 1f});
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        if (radius <= 0f) {
            return;
        }

        // Softly lit face and a fading sweep fan add depth without obscuring the grid.
        paint.setStyle(Paint.Style.FILL);
        paint.setShader(fieldShader);
        canvas.drawCircle(cx, cy, radius, paint);
        paint.setShader(null);
        sweepMatrix.setRotate(angle, cx, cy);
        sweepShader.setLocalMatrix(sweepMatrix);
        paint.setShader(sweepShader);
        canvas.drawCircle(cx, cy, radius, paint);
        paint.setShader(null);

        // Fine radial grid and range rings.
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1));
        paint.setColor(0x5272D8B3);
        canvas.drawCircle(cx, cy, radius, paint);
        paint.setColor(0x3272D8B3);
        canvas.drawCircle(cx, cy, radius * .75f, paint);
        canvas.drawCircle(cx, cy, radius * .50f, paint);
        canvas.drawCircle(cx, cy, radius * .25f, paint);
        paint.setColor(0x2872D8B3);
        for (int spoke = 0; spoke < 8; spoke++) {
            double radians = Math.toRadians(spoke * 45f);
            float x = (float) Math.cos(radians) * radius;
            float y = (float) Math.sin(radians) * radius;
            canvas.drawLine(cx - x, cy - y, cx + x, cy + y, paint);
        }

        // Short perimeter ticks and cardinal marks make the display feel like an instrument.
        paint.setColor(0x6872D8B3);
        paint.setStrokeWidth(dp(1.2f));
        for (int tick = 0; tick < 48; tick++) {
            double radians = Math.toRadians(tick * 7.5f);
            float inner = radius - (tick % 6 == 0 ? dp(7) : dp(3));
            float x1 = cx + (float) Math.cos(radians) * inner;
            float y1 = cy + (float) Math.sin(radians) * inner;
            float x2 = cx + (float) Math.cos(radians) * radius;
            float y2 = cy + (float) Math.sin(radians) * radius;
            canvas.drawLine(x1, y1, x2, y2, paint);
        }
        paint.setStyle(Paint.Style.FILL);
        paint.setTextSize(dp(8));
        paint.setColor(0xA6A8C8C8);
        drawDirection(canvas, "N", cx, cy - radius - dp(5), true);
        drawDirection(canvas, "E", cx + radius + dp(5), cy, false);
        drawDirection(canvas, "S", cx, cy + radius + dp(11), true);
        drawDirection(canvas, "W", cx - radius - dp(5), cy, false);

        // A translucent trailing sector and a bright leading beam rotate together.
        canvas.save();
        canvas.rotate(angle, cx, cy);
        sweepWedge.reset();
        sweepWedge.moveTo(cx, cy);
        sweepWedge.lineTo(cx + radius, cy);
        sweepWedge.arcTo(radarBounds, 0f, -34f, false);
        sweepWedge.close();
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x1E72D8B3);
        canvas.drawPath(sweepWedge, paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeCap(Paint.Cap.ROUND);
        paint.setStrokeWidth(dp(5));
        paint.setColor(0x3872D8B3);
        canvas.drawLine(cx, cy, cx + radius, cy, paint);
        paint.setStrokeWidth(dp(1.8f));
        paint.setColor(0xFFE0FFF2);
        canvas.drawLine(cx, cy, cx + radius, cy, paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(ACCENT);
        canvas.drawCircle(cx + radius, cy, dp(2.2f), paint);
        canvas.restore();

        // Station echoes brighten briefly as the sweep crosses their bearing.
        for (int i = 0; i < TARGET_BEARINGS.length; i++) {
            drawTarget(canvas, cx, cy, i);
        }

        // Center hub.
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x3672D8B3);
        canvas.drawCircle(cx, cy, dp(10), paint);
        paint.setColor(0xFFB8F5DB);
        canvas.drawCircle(cx, cy, dp(3.2f), paint);

        if (isAttachedToWindow() && getVisibility() == VISIBLE
                && ValueAnimator.areAnimatorsEnabled()) {
            long now = SystemClock.uptimeMillis();
            if (lastFrameTime != 0L) {
                long elapsed = Math.min(80L, now - lastFrameTime);
                angle = (angle + elapsed * .08f) % 360f;
            }
            lastFrameTime = now;
            postInvalidateOnAnimation();
        } else {
            lastFrameTime = 0L;
        }
    }

    private void drawDirection(Canvas canvas, String label, float x, float y,
                               boolean centered) {
        paint.setTextSize(dp(8));
        if (centered) {
            x -= paint.measureText(label) / 2f;
        }
        canvas.drawText(label, x, y, paint);
    }

    private void drawTarget(Canvas canvas, float cx, float cy, int index) {
        double radians = Math.toRadians(TARGET_BEARINGS[index]);
        float distance = radius * TARGET_RANGES[index];
        float x = cx + (float) Math.cos(radians) * distance;
        float y = cy + (float) Math.sin(radians) * distance;
        float elapsedSweep = (angle - TARGET_BEARINGS[index] + 360f) % 360f;
        float strength = Math.max(0f, 1f - elapsedSweep / 78f);

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x2872D8B3);
        canvas.drawCircle(x, y, dp(5) + dp(3) * strength, paint);
        paint.setColor(ACCENT);
        paint.setAlpha(70 + Math.round(185 * strength));
        canvas.drawCircle(x, y, dp(1.8f) + dp(1.2f) * strength, paint);
        paint.setAlpha(255);
    }

    private float dp(float px) {
        return px * getResources().getDisplayMetrics().density;
    }
}
