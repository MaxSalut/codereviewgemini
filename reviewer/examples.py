"""Демо-приклади для захисту: у кожному є кілька очевидних помилок, поганих практик і проблем стилю."""

EXAMPLES = [
    {
        "id": "python-grades",
        "title": "Python: середній бал групи",
        "language": "python",
        "filename": "lab3_grades.py",
        "hint": "ділення на нуль, змінюваний аргумент за замовчуванням, незакритий файл",
        "code": '''def load_grades(path, grades=[]):
    f = open(path)
    for line in f:
        name, mark = line.split(",")
        grades.append(int(mark))
    return grades


def average(grades):
    total = 0
    for i in range(len(grades)):
        total = total + grades[i]
    return total / len(grades)


def best_student(data):
    best = None
    for name in data:
        if best == None or data[name] > data[best]:
            best = name
    return best


try:
    g = load_grades("grades.csv")
    print("Середній бал:", average(g))
    print("Порожня група:", average([]))
except:
    pass
''',
    },
    {
        "id": "cpp-array",
        "title": "C++: масив і пошук максимуму",
        "language": "cpp",
        "filename": "lab2_array.cpp",
        "hint": "вихід за межі масиву, витік пам'яті, неініціалізована змінна",
        "code": '''#include <iostream>
using namespace std;

int findMax(int* a, int n) {
    int max;
    for (int i = 0; i <= n; i++) {
        if (a[i] > max) max = a[i];
    }
    return max;
}

int main() {
    int n;
    cout << "Enter n: ";
    cin >> n;
    int* arr = new int[n];
    for (int i = 0; i < n; i++) {
        cin >> arr[i];
    }
    int sum = 0;
    for (int i = 0; i < n; i++) sum += arr[i];
    cout << "Max: " << findMax(arr, n) << endl;
    cout << "Avg: " << sum / n << endl;
    return 0;
}
''',
    },
    {
        "id": "java-login",
        "title": "Java: перевірка логіна",
        "language": "java",
        "filename": "Lab4Login.java",
        "hint": "порівняння рядків через ==, SQL-ін'єкція, незакритий Scanner",
        "code": '''import java.sql.*;
import java.util.Scanner;

public class Lab4Login {
    static String ADMIN = "admin";

    public static boolean login(Connection conn, String user, String pass) throws Exception {
        Statement st = conn.createStatement();
        ResultSet rs = st.executeQuery(
            "SELECT * FROM users WHERE name = '" + user + "' AND password = '" + pass + "'");
        return rs.next();
    }

    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        String user = sc.nextLine();
        if (user == ADMIN) {
            System.out.println("Hello, admin");
        }
        try {
            Connection conn = DriverManager.getConnection("jdbc:mysql://localhost/lab", "root", "12345");
            if (login(conn, user, sc.nextLine())) System.out.println("OK");
        } catch (Exception e) {
        }
    }
}
''',
    },
    {
        "id": "js-fetch",
        "title": "JavaScript: завантаження списку студентів",
        "language": "javascript",
        "filename": "lab5_students.js",
        "hint": "async у forEach, == замість ===, немає обробки помилок",
        "code": '''var students = [];

async function loadStudents(ids) {
    ids.forEach(async (id) => {
        const res = await fetch("/api/students/" + id);
        const data = await res.json();
        students.push(data);
    });
    console.log("Loaded:", students.length);
    return students;
}

function findByGroup(group) {
    var result = [];
    for (var i = 0; i < students.length; i++) {
        if (students[i].group == group) result.push(students[i]);
    }
    return result;
}

function render(list) {
    document.getElementById("list").innerHTML = list.map(s => "<li>" + s.name + "</li>").join("");
}

loadStudents([1, 2, 3]).then(() => render(findByGroup("TK-42")));
''',
    },
]
