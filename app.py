from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import pyodbc

app = Flask(__name__)
CORS(app) # Cho phép Web gọi API

# Giao diện Trang chủ Web
@app.route('/')
def home():
    return render_template('index.html')

# Thiết lập kết nối đến SQL Server (Dùng Windows Authentication)
def get_db_connection():
    # Lưu ý: Nếu SQL Server của bạn có tên là SQLEXPRESS, hãy đổi 'localhost' thành 'localhost\\SQLEXPRESS'
    conn = pyodbc.connect(
        'Driver={SQL Server};'
        'Server=DESKTOP-V8SKLAG\\MSSQLSERVER01;'
        'Database=parking_management;'
        'Trusted_Connection=yes;'
    )
    return conn

# API 1: Lấy danh sách xe đang trong bãi
@app.route('/api/xe-trong-bai', methods=['GET'])
def get_xe_trong_bai():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT LG.MaLuot, LG.BienSo, TX.LoaiThe, ISNULL(KH.Ten, N'Khách vãng lai') as ChuXe, LG.ThoiGianVao
        FROM LuotGui LG
        JOIN Xe X ON LG.BienSo = X.BienSo
        LEFT JOIN KhachHang KH ON X.MaKH = KH.MaKH
        JOIN TheXe TX ON LG.MaThe = TX.MaThe
        WHERE LG.ThoiGianRa IS NULL
        ORDER BY LG.ThoiGianVao DESC
    """)
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append({
            'MaLuot': row.MaLuot,
            'BienSo': row.BienSo,
            'LoaiThe': row.LoaiThe,
            'ChuXe': row.ChuXe,
            'GioVao': row.ThoiGianVao.strftime("%d/%m/%Y %H:%M:%S")
        })
    conn.close()
    return jsonify(result)

# API 2: Cho xe vào bãi
@app.route('/api/cho-xe-vao', methods=['POST'])
def cho_xe_vao():
    data = request.json
    ma_the = data.get('maThe')
    bien_so = data.get('bienSo')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # BƯỚC 1: Kiểm tra xem xe này đã có "hộ khẩu" trong bảng Xe chưa?
        cursor.execute("SELECT COUNT(*) FROM Xe WHERE BienSo = ?", (bien_so,))
        if cursor.fetchone()[0] == 0:
            # VÁ LỖI Ở ĐÂY: Thêm LoaiXe mặc định là 'Ô tô' để SQL Server không báo lỗi NULL
            cursor.execute("INSERT INTO Xe (BienSo, LoaiXe) VALUES (?, N'Ô tô')", (bien_so,))
            
        # BƯỚC 2: Cấp lượt gửi vào bãi
        cursor.execute("""
            INSERT INTO LuotGui (MaThe, BienSo, MaNV, MaLanVao, MaGia, ThoiGianVao)
            VALUES (?, ?, 'NV01', 'LAN1_IN', 'GIA_OT_NGAY', GETDATE())
        """, (ma_the, bien_so))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Cho xe vào thành công!"}), 200
    except Exception as e:
        print("❌ LỖI SQL:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 400
    
# API 3: Cho xe ra khỏi bãi (Tính tiền và cập nhật giờ ra)
@app.route('/api/cho-xe-ra', methods=['POST'])
def cho_xe_ra():
    data = request.json
    ma_the = data.get('maThe')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Kiểm tra xem thẻ này có thực sự đang trong bãi không?
        cursor.execute("SELECT MaLuot FROM LuotGui WHERE MaThe = ? AND ThoiGianRa IS NULL", (ma_the,))
        if not cursor.fetchone():
            return jsonify({"status": "error", "message": "Thẻ này không có trong bãi hoặc đã ra rồi!"}), 400
            
        # 2. Thực hiện Cho Xe Ra: Cập nhật Giờ ra và Tính tiền tự động
        cursor.execute("""
            UPDATE LuotGui 
            SET ThoiGianRa = GETDATE(),
                MaLanRa = 'LAN1_OUT',
                TongTien = (SELECT DonGia FROM BangGia WHERE MaGia = LuotGui.MaGia)
            WHERE MaThe = ? AND ThoiGianRa IS NULL
        """, (ma_the,))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Cho xe ra thành công! Đã chốt ca."}), 200
    except Exception as e:
        print("❌ LỖI SQL (XE RA):", str(e))
        return jsonify({"status": "error", "message": str(e)}), 400

# API 4: Đăng nhập
@app.route('/api/dang-nhap', methods=['POST'])
def dang_nhap():
    data = request.json
    ma_nv = data.get('ma_nv')
    mat_khau = data.get('mat_khau')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Tìm xem có nhân viên nào khớp mã và mật khẩu không
        cursor.execute("SELECT Ten FROM NhanVien WHERE MaNV = ? AND MatKhau = ?", (ma_nv, mat_khau))
        nhan_vien = cursor.fetchone()
        
        if nhan_vien:
            return jsonify({"status": "success", "message": "Đăng nhập thành công", "ten_nv": nhan_vien[0]})
        else:
            return jsonify({"status": "error", "message": "Sai mã nhân viên hoặc mật khẩu!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    finally:
        if 'conn' in locals():
            conn.close()

# API 5: Xem lịch sử giao dịch (Cho Admin)
@app.route('/api/lich-su', methods=['GET'])
def get_lich_su():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Lấy 100 giao dịch mới nhất để Admin dễ xem
        cursor.execute("""
            SELECT TOP 100 MaLuot, BienSo, MaThe, ThoiGianVao, ThoiGianRa, TongTien, NguoiThuTien
            FROM LuotGui
            ORDER BY ThoiGianVao DESC
        """)
        rows = cursor.fetchall()
        
        lich_su = []
        for row in rows:
            lich_su.append({
                "MaLuot": row.MaLuot,
                "BienSo": row.BienSo,
                "MaThe": row.MaThe,
                "ThoiGianVao": row.ThoiGianVao.strftime("%d/%m/%Y %H:%M:%S") if row.ThoiGianVao else "",
                "ThoiGianRa": row.ThoiGianRa.strftime("%d/%m/%Y %H:%M:%S") if row.ThoiGianRa else "Đang trong bãi",
                "TongTien": float(row.TongTien) if row.TongTien else 0,
                "NguoiThuTien": row.NguoiThuTien if row.NguoiThuTien else "Chưa ghi nhận"
            })
        return jsonify(lich_su)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    finally:
        if 'conn' in locals():
            conn.close()

# API 6: Khóa thẻ khẩn cấp
@app.route('/api/khoa-the', methods=['POST'])
def khoa_the():
    data = request.json
    ma_the = data.get('ma_the')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE TheXe SET TrangThaiKhoa = 1 WHERE MaThe = ?", (ma_the,))
        conn.commit()
        
        return jsonify({"status": "success", "message": f"Đã khóa thẻ {ma_the} thành công! Kẻ gian không thể sử dụng."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    print("🚀 Server đang khởi động tại http://127.0.0.1:5000")
    app.run(debug=True, port=5000)