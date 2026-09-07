package jp.myproject.messenger;

import android.os.Bundle;
import android.view.WindowManager;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    /**
     * 画面の撮影・録画をさせない設定。
     *
     * FLAG_SECURE を立てると、この端末では次のようになる。
     *   - スクリーンショットと画面録画ができなくなる
     *   - アプリ切り替えの一覧に、会話の内容が写らなくなる
     *
     * 「消えるメッセージ」を意味のあるものにするために既定で有効にしている。
     * ただし、別のカメラで画面を直接撮影されることまでは防げない。
     *
     * スクリーンショットを撮れるようにしたい場合は、下の1行を削除して作り直す。
     */
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
    }
}
