package nl.eyevisions.sdrcc.mobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;

/** Small native radar sweep for the branded connection screen. */
public final class RadarView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private float angle = 0f;

    public RadarView(Context context) {
        super(context);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        float radius = Math.max(0f, Math.min(cx, cy) - dp(8));
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1));
        paint.setColor(0x4B72D8B3);
        canvas.drawCircle(cx, cy, radius, paint);
        canvas.drawCircle(cx, cy, radius * .66f, paint);
        canvas.drawCircle(cx, cy, radius * .33f, paint);
        paint.setColor(0x3372D8B3);
        canvas.drawLine(cx - radius, cy, cx + radius, cy, paint);
        canvas.drawLine(cx, cy - radius, cx, cy + radius, paint);

        canvas.save();
        canvas.rotate(angle, cx, cy);
        paint.setStrokeWidth(dp(2));
        paint.setColor(0xFF72D8B3);
        canvas.drawLine(cx, cy, cx + radius, cy, paint);
        canvas.restore();

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0xFF72D8B3);
        canvas.drawCircle(cx, cy, dp(3), paint);
        angle = (angle + 3f) % 360f;
        if (isAttachedToWindow() && getVisibility() == VISIBLE) {
            postInvalidateDelayed(45);
        }
    }

    private float dp(float px) {
        return px * getResources().getDisplayMetrics().density;
    }
}
